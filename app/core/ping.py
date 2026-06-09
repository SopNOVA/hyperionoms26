import subprocess
import re
import platform
from typing import Optional, Tuple
from icmplib import ping as icmp_ping, ICMPLibError

def robust_ping(ip_address: str, count: int = 2, timeout: int = 2) -> Tuple[bool, Optional[int], Optional[str]]:
    """
    Robust ping that tries icmplib first (cross-platform attempt),
    then falls back to system 'ping' command (which works for the user as shown in shell).
    Returns: (is_alive, avg_rtt_ms or None, error_message or None)
    """
    # First try icmplib (the original method)
    try:
        result = icmp_ping(ip_address, count=count, interval=0.2, timeout=timeout, privileged=False)
        if result.is_alive:
            rtt = int(result.avg_rtt)
            return True, rtt, None
        else:
            # Not alive, but no exception - try system anyway for accuracy
            pass
    except (ICMPLibError, Exception) as e:
        # icmplib failed (common with privileged=False on some Linux setups for private IPs)
        pass

    # Fallback to system ping - this matches exactly what user runs in shell and succeeds
    try:
        system = platform.system().lower()
        if system == "windows":
            # Windows ping
            cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), ip_address]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=timeout * count + 1)
            # Parse Windows: "Average = 2ms" or "tiempo medio = "
            match = re.search(r"(?:Average|tiempo medio|Media)\s*=\s*(\d+)", output, re.IGNORECASE)
            if match:
                rtt = int(match.group(1))
                return True, rtt, None
            if "TTL=" in output or "tiempo=" in output.lower():
                # At least some replies
                return True, 1, None  # unknown exact, but alive
            return False, None, "no reply"
        else:
            # Linux / macOS / Unix
            cmd = ["ping", "-c", str(count), "-W", str(timeout), ip_address]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=timeout * count + 2)
            # Look for rtt min/avg/max/mdev = 1.269/1.313/1.358/0.044 ms  (handle Spanish too)
            match = re.search(r"(?:rtt|min/avg/max/mdev)\s*=\s*[\d.]+/([\d.]+)/", output, re.IGNORECASE)
            if match:
                avg = float(match.group(1))
                return True, int(avg), None
            # Fallback parse for received packets
            if "2 received" in output or "1 received" in output or "recibidos" in output.lower():
                # Try to find any time= or tiempo= 
                times = re.findall(r"(?:time|tiempo)=([\d.]+)", output, re.IGNORECASE)
                if times:
                    avg = sum(float(t) for t in times) / len(times)
                    return True, int(avg), None
                return True, 1, None
            return False, None, "no reply in output"
    except subprocess.CalledProcessError as e:
        # ping returned non-zero (no reply or error)
        err = e.output if isinstance(e.output, str) else str(e)
        return False, None, f"system ping failed: {err[:100]}"
    except subprocess.TimeoutExpired:
        return False, None, "timeout"
    except Exception as e:
        return False, None, str(e)[:100]
