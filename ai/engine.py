"""
KaunHaiBe - AI Engine
Primary: Ollama (qwen2.5:14b) via REST
Fallback: Rule-based expert system
Optimized for Windows 11 Pro 25H2 system analysis
"""
import json
import os
import time
import threading
import requests

OLLAMA_URL = "http://localhost:11434"
PREFERRED_MODELS = ["qwen2.5:14b", "qwen2.5:7b", "llama3.1:8b", "mistral:7b", "gemma2:9b"]

SYSTEM_PROMPT = """You are KaunHaiBe, an expert Windows system diagnostics AI running locally on:
- AMD Ryzen 5 7600X | 64GB RAM | RTX 3050 8GB | Windows 11 Pro 25H2
You analyze real-time system vitals to find lags, bottlenecks, crashes, and anomalies.
You have access to live CPU, GPU, disk, RAM, process, service, interrupt, registry, and event log data.
Be concise, technical, and actionable. Format findings as bullet points when listing issues.
Respond in plain text. No markdown. Speak like a sharp system engineer.
"""


class AIEngine:
    def __init__(self):
        self._ollama_available = False
        self._active_model = None
        self._lock = threading.Lock()
        self._context_vitals = {}

        # Check Ollama in background
        t = threading.Thread(target=self._probe_ollama, daemon=True)
        t.start()

    def _probe_ollama(self):
        """Probe Ollama, launch server if not running, and find best available model."""
        import subprocess
        for attempt in range(20):  # retry for up to ~60s after startup
            try:
                r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
                if r.status_code == 200:
                    data = r.json()
                    installed = [m["name"] for m in data.get("models", [])]
                    # Find best preferred model
                    for preferred in PREFERRED_MODELS:
                        for inst in installed:
                            if preferred.split(":")[0] in inst:
                                self._active_model = inst
                                self._ollama_available = True
                                return
                    if installed:
                        self._active_model = installed[0]
                        self._ollama_available = True
                        return
            except Exception:
                if attempt == 0:
                    # Try auto-starting Ollama serve in background
                    try:
                        ollama_exe = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
                        if os.path.exists(ollama_exe):
                            subprocess.Popen([ollama_exe, "serve"], creationflags=subprocess.CREATE_NO_WINDOW)
                    except Exception:
                        pass
            time.sleep(2)

    def set_vitals_context(self, vitals: dict):
        """Update live vitals context for AI chat."""
        with self._lock:
            self._context_vitals = vitals

    def is_online(self):
        return self._ollama_available

    def get_model_name(self):
        return self._active_model or "Rule-Based Engine"

    def _build_vitals_summary(self, vitals: dict) -> str:
        """Convert vitals dict to compact text for AI context."""
        lines = ["=== LIVE SYSTEM VITALS ==="]
        try:
            c = vitals.get("cpu", {})
            if c:
                lines.append(f"CPU: {c.get('usage_total', 0):.1f}% | {c.get('freq_current_mhz', 0):.0f}MHz | "
                             f"User:{c.get('user_pct',0):.1f}% Sys:{c.get('system_pct',0):.1f}% Idle:{c.get('idle_pct',0):.1f}% "
                             f"IRQ:{c.get('interrupt_pct',0):.1f}% DPC:{c.get('dpc_pct',0):.1f}%")

            g = vitals.get("gpu", {})
            gpus = g.get("gpus", [])
            if gpus:
                gg = gpus[0]
                lines.append(f"GPU: {gg.get('name','?')} | Load:{gg.get('usage_pct',0)}% | "
                             f"Mem:{gg.get('mem_usage_pct',0)}% ({gg.get('mem_used_mb',0):.0f}/{gg.get('mem_total_mb',0):.0f}MB) | "
                             f"Temp:{gg.get('temp_c','?')}°C")

            mb = vitals.get("motherboard", {})
            ram = mb.get("ram", {})
            if ram:
                lines.append(f"RAM: {ram.get('usage_pct',0)}% | Used:{ram.get('used_gb',0):.1f}GB / {ram.get('total_gb',0):.1f}GB")
            swap = mb.get("swap", {})
            if swap and swap.get("total_gb", 0) > 0:
                lines.append(f"Swap: {swap.get('usage_pct',0)}% used")

            d = vitals.get("disk", {})
            if d:
                lines.append(f"Disk I/O: Read:{d.get('max_read_mbps',0):.1f}MB/s Write:{d.get('max_write_mbps',0):.1f}MB/s")

            intr = vitals.get("interrupts", {})
            if intr:
                lines.append(f"Interrupts/s: {intr.get('interrupts_per_sec',0):,} | DPC/s: {intr.get('dpc_per_sec',0):,} "
                             f"| IRQ%: {intr.get('pct_interrupt',0):.1f} | DPC%: {intr.get('pct_dpc',0):.1f}")

            kern = vitals.get("kernel", {})
            if kern:
                lines.append(f"System: {kern.get('process_count',0)} processes | Uptime: {kern.get('uptime_hours',0):.1f}h | "
                             f"Ctx-switches: {kern.get('ctx_switches',0):,}")

            # Top processes
            proc = vitals.get("processes", {})
            top = proc.get("top_cpu", [])
            if top:
                top_str = " | ".join(f"{p['name']}({p['cpu_pct']:.1f}%)" for p in top[:5])
                lines.append(f"Top CPU procs: {top_str}")
            top_r = proc.get("top_ram", [])
            if top_r:
                top_str = " | ".join(f"{p['name']}({p['ram_mb']:.0f}MB)" for p in top_r[:5])
                lines.append(f"Top RAM procs: {top_str}")

            # Event log errors
            evlog = vitals.get("eventlog", {})
            errors = [e for e in evlog.get("entries", []) if e.get("type") == "Error"][:3]
            if errors:
                lines.append("Recent System Errors:")
                for e in errors:
                    lines.append(f"  [{e.get('source','')}] {e.get('message','')[:80]}")

        except Exception as e:
            lines.append(f"(vitals parse error: {e})")

        return "\n".join(lines)

    def chat(self, user_message: str, stream_callback=None) -> str:
        """
        Send a message to AI. If stream_callback is provided, streams tokens.
        Returns full response string.
        """
        with self._lock:
            vitals = dict(self._context_vitals)

        vitals_summary = self._build_vitals_summary(vitals)
        full_prompt = f"{vitals_summary}\n\n=== USER QUERY ===\n{user_message}"

        if self._ollama_available and self._active_model:
            return self._ollama_chat(full_prompt, stream_callback)
        else:
            return self._rule_based_chat(user_message, vitals)

    def _ollama_chat(self, prompt: str, stream_callback=None) -> str:
        """Stream from Ollama."""
        payload = {
            "model": self._active_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt}
            ],
            "stream": True,
            "options": {
                "temperature": 0.2,
                "num_ctx": 2048,   # Reduced from 8192 for 4x faster response startup & generation
                "num_predict": 512, # Cap generation length for snappy response
                "num_gpu": 99,     # Offload all layers to RTX 3050 GPU
            }
        }
        full_response = ""
        try:
            with requests.post(f"{OLLAMA_URL}/api/chat", json=payload,
                               stream=True, timeout=120) as resp:
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        token = obj.get("message", {}).get("content", "")
                        if token:
                            full_response += token
                            if stream_callback:
                                stream_callback(token)
                        if obj.get("done"):
                            break
                    except Exception:
                        continue
        except Exception as e:
            full_response = f"[Ollama error: {e}]\n\n" + self._rule_based_chat("", self._context_vitals)

        return full_response

    def _rule_based_chat(self, message: str, vitals: dict) -> str:
        """Smart rule-based fallback analysis."""
        msg = message.lower()
        lines = []

        c  = vitals.get("cpu", {})
        g  = vitals.get("gpu", {})
        d  = vitals.get("disk", {})
        mb = vitals.get("motherboard", {})
        intr = vitals.get("interrupts", {})
        proc = vitals.get("processes", {})

        cpu_usage = c.get("usage_total", 0)
        gpu_usage = g.get("usage_pct", 0) or 0
        ram_usage = mb.get("ram", {}).get("usage_pct", 0) if mb.get("ram") else 0
        disk_read = d.get("max_read_mbps", 0)
        disk_write = d.get("max_write_mbps", 0)
        irq_ps = intr.get("interrupts_per_sec", 0)
        dpc_ps = intr.get("dpc_per_sec", 0)

        if any(k in msg for k in ["lag", "slow", "freeze", "stutter", "spike", "why"]):
            lines.append("DIAGNOSIS: Analyzing current lag sources...")
            issues = []
            if cpu_usage > 80:
                top = proc.get("top_cpu", [])[:3]
                hogs = ", ".join(f"{p['name']}({p['cpu_pct']:.1f}%)" for p in top)
                issues.append(f"CPU at {cpu_usage:.1f}% — hogged by: {hogs}")
            if gpu_usage > 85:
                issues.append(f"GPU at {gpu_usage:.1f}% — likely rendering bottleneck or runaway GPU process")
            if ram_usage > 85:
                issues.append(f"RAM at {ram_usage:.1f}% — system paging to disk, causing stutters")
            if disk_read > 150 or disk_write > 150:
                issues.append(f"Disk thrashing: Read {disk_read:.1f} MB/s | Write {disk_write:.1f} MB/s")
            if irq_ps > 50000:
                issues.append(f"Interrupt storm: {irq_ps:,}/s — check USB/network drivers")
            if dpc_ps > 10000:
                issues.append(f"High DPC rate: {dpc_ps:,}/s — likely driver issue (network or audio)")
            if not issues:
                issues.append("No major bottlenecks detected currently. System appears stable.")
            for i in issues:
                lines.append(f"  > {i}")

        elif any(k in msg for k in ["cpu", "processor"]):
            lines.append(f"CPU Status: {cpu_usage:.1f}% usage | {c.get('freq_current_mhz', 0):.0f} MHz")
            lines.append(f"  IRQ: {c.get('interrupt_pct',0):.1f}% | DPC: {c.get('dpc_pct',0):.1f}%")
            top = proc.get("top_cpu", [])[:5]
            for p in top:
                lines.append(f"  {p['name']:30s} {p['cpu_pct']:5.1f}%  PID:{p['pid']}")

        elif any(k in msg for k in ["gpu", "graphics", "video"]):
            gpus = g.get("gpus", [])
            if gpus:
                gg = gpus[0]
                lines.append(f"GPU: {gg.get('name','?')}")
                lines.append(f"  Usage: {gg.get('usage_pct',0)}% | Temp: {gg.get('temp_c','?')}°C")
                lines.append(f"  VRAM: {gg.get('mem_used_mb',0):.0f}/{gg.get('mem_total_mb',0):.0f} MB ({gg.get('mem_usage_pct',0):.1f}%)")
            else:
                lines.append("No GPU data available.")

        elif any(k in msg for k in ["ram", "memory"]):
            ram = mb.get("ram", {})
            lines.append(f"RAM: {ram.get('used_gb',0):.1f} / {ram.get('total_gb',0):.1f} GB ({ram.get('usage_pct',0):.1f}%)")
            top = proc.get("top_ram", [])[:5]
            for p in top:
                lines.append(f"  {p['name']:30s} {p['ram_mb']:7.1f} MB")

        elif any(k in msg for k in ["disk", "hdd", "ssd", "storage", "io"]):
            lines.append(f"Disk I/O: Read {disk_read:.1f} MB/s | Write {disk_write:.1f} MB/s")
            smart = d.get("smart", {})
            for name, data in smart.items():
                if name == "error":
                    continue
                lines.append(f"  {name}: Health={data.get('health','?')} Temp={data.get('temperature','?')}°C")

        elif any(k in msg for k in ["process", "proc", "task", "hogging", "hog"]):
            lines.append("Top Processes by CPU:")
            for p in proc.get("top_cpu", [])[:10]:
                lines.append(f"  PID:{p['pid']:6} {p['name']:30s} CPU:{p['cpu_pct']:5.1f}% RAM:{p['ram_mb']:.0f}MB")

        elif any(k in msg for k in ["interrupt", "irq", "dpc"]):
            lines.append(f"Interrupts: {irq_ps:,}/s | DPC: {dpc_ps:,}/s")
            lines.append(f"IRQ Time: {intr.get('pct_interrupt',0):.2f}% | DPC Time: {intr.get('pct_dpc',0):.2f}%")
            if dpc_ps > 8000:
                lines.append("  WARNING: Elevated DPC — common causes: network driver, audio driver, storage controller")

        elif any(k in msg for k in ["hello", "hi", "hey"]):
            lines.append("KaunHaiBe online. System monitoring active.")
            lines.append(f"AI Mode: Rule-Based (Ollama not detected)")
            lines.append(f"Watching: CPU {cpu_usage:.1f}% | GPU {gpu_usage:.1f}% | RAM {ram_usage:.1f}%")

        else:
            lines.append("KaunHaiBe - Commands I understand:")
            lines.append("  'why is my pc lagging?' — diagnose lag")
            lines.append("  'cpu status' — CPU details")
            lines.append("  'gpu status' — GPU details")
            lines.append("  'ram usage' — memory breakdown")
            lines.append("  'disk io' — disk read/write")
            lines.append("  'top processes' — CPU/RAM hogs")
            lines.append("  'interrupt status' — DPC/IRQ analysis")
            lines.append(f"[Ollama status: {'Online - ' + (self._active_model or '') if self._ollama_available else 'Not detected — install Ollama for full AI'}]")

        return "\n".join(lines)

    def analyze_for_report(self, vitals: dict, events: list) -> str:
        """Generate automated system health report."""
        summary = self._build_vitals_summary(vitals)
        recent_events = "\n".join(
            f"[{e.get('time','')}] {e.get('type','')}: {e.get('message','')}"
            for e in events[-20:]
        )
        prompt = f"{summary}\n\nRECENT EVENTS:\n{recent_events}\n\nGenerate a concise system health report with: 1) Current status, 2) Any anomalies, 3) Predicted causes of issues, 4) Recommendations."

        if self._ollama_available:
            return self._ollama_chat(prompt)
        else:
            return self._rule_based_chat("why is my pc lagging", vitals)
