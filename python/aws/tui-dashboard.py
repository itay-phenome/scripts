from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.layout import Layout
import psutil
import socket
import docker
import os
import time

console = Console()

def get_ip_address():
    addrs = psutil.net_if_addrs()
    for iface in ["eth0", "wlan0"]:
        if iface in addrs:
            for addr in addrs[iface]:
                if addr.family == socket.AF_INET:
                    return addr.address
    return "N/A"

def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return int(f.read()) / 1000
    except:
        return 0.0

def get_system_info():
    hostname = socket.gethostname()
    ip = get_ip_address()
    temp = get_cpu_temp()
    load1, load5, load15 = os.getloadavg()
    return hostname, ip, temp, (load1, load5, load15)

def get_cpu_usage():
    return psutil.cpu_percent(percpu=True)

def get_memory_usage():
    mem = psutil.virtual_memory()
    return mem.percent, mem.used // 1024**2, mem.total // 1024**2

def get_disk_usage():
    disk = psutil.disk_usage('/')
    return disk.percent, disk.used // 1024**3, disk.total // 1024**3

def get_network_info():
    net = psutil.net_io_counters()
    return net.bytes_sent, net.bytes_recv

def get_docker_info():
    client = docker.from_env()
    containers = client.containers.list(all=True)
    info_lines = []
    error_lines = []

    for container in containers:
        name = container.name
        status = container.status

        try:
            stats = container.stats(stream=False)
            cpu_total = stats["cpu_stats"]["cpu_usage"].get("total_usage", 0)
            cpu_prev = stats["precpu_stats"]["cpu_usage"].get("total_usage", 0)
            sys_total = stats["cpu_stats"].get("system_cpu_usage", 1)
            sys_prev = stats["precpu_stats"].get("system_cpu_usage", 1)
            cpu_percent = ((cpu_total - cpu_prev) / (sys_total - sys_prev)) * 100 if (sys_total - sys_prev) > 0 else 0.0

            mem_usage = stats["memory_stats"].get("usage", 0) / (1024 * 1024)

            info_lines.append(f"{name:<12} | {status:<7} | CPU: {cpu_percent:>4.1f}% | RAM: {mem_usage:>4.0f}MB")

            logs = container.logs(tail=30).decode(errors="ignore").splitlines()
            errors = [line for line in logs if any(w in line.lower() for w in ["error", "failed", "exited"])]
            for err in errors[-3:]:
                error_lines.append(f"[{name}] {err.strip()}")

        except Exception as e:
            info_lines.append(f"{name:<12} | {status:<7} | Stats unavailable")
            error_lines.append(f"[{name}] Error: {str(e)}")

    return "\n".join(info_lines), "\n".join(error_lines[-10:])

def make_dashboard():
    hostname, ip, temp, load = get_system_info()
    cpu = get_cpu_usage()
    ram_percent, ram_used, ram_total = get_memory_usage()
    disk_percent, disk_used, disk_total = get_disk_usage()
    net_sent, net_recv = get_network_info()
    docker_stats, docker_errors = get_docker_info()

    layout = Layout()
    layout.split_column(
        Layout(name="top"),
        Layout(name="middle"),
        Layout(name="bottom")
    )

    system_info = Panel(
        f"Host: [bold cyan]{hostname}[/]\nIP: [bold magenta]{ip}[/]\nTemp: {temp:.1f}°C\nLoad Avg: {load[0]:.1f}, {load[1]:.1f}, {load[2]:.1f}",
        title="System Info", border_style="blue"
    )

    cpu_info = Panel("\n".join([f"CPU{i}: {p:4.1f}%" for i, p in enumerate(cpu)]), title="CPU Usage", border_style="green")
    ram_info = Panel(f"RAM: {ram_percent:.1f}% ({ram_used}MB / {ram_total}MB)", title="RAM", border_style="blue")
    disk_info = Panel(f"Disk: {disk_percent:.1f}% ({disk_used}GB / {disk_total}GB)", title="Disk", border_style="magenta")
    net_info = Panel(f"Sent: {net_sent // 1024} KB\nRecv: {net_recv // 1024} KB", title="Network", border_style="cyan")

    docker_panel = Panel(docker_stats or "No containers", title="[bold underline green]Docker Containers[/]", border_style="cyan")
    error_panel = Panel(docker_errors or "No recent errors", title="[bold underline red]Container Error Logs[/]", border_style="red")

    layout["top"].update(system_info)
    layout["middle"].split_row(cpu_info, ram_info, disk_info, net_info)
    layout["bottom"].split_column(docker_panel, error_panel)

    return layout

if __name__ == "__main__":
    with Live(make_dashboard(), refresh_per_second=1, screen=True) as live:
        while True:
            live.update(make_dashboard())
            time.sleep(3)

