import os
import sys
import threading
import traceback


class _BosAkim:
    def write(self, s):
        return len(s) if s else 0

    def flush(self):
        pass

    def isatty(self):
        return False


for _ad in ("stdout", "stderr"):
    _akim = getattr(sys, _ad, None)
    if _akim is None or isinstance(_akim, str) or not hasattr(_akim, "write"):
        setattr(sys, _ad, _BosAkim())

try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
except Exception:
    pass

import yt_dlp
from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput


class SessizGunluk:
    def __init__(self):
        self.son_hata = ""

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        self.son_hata = str(msg)


def indirme_klasoru():
    try:
        from android.storage import primary_external_storage_path
        yol = os.path.join(primary_external_storage_path(), "Download")
    except ImportError:
        yol = os.path.expanduser("~/Downloads")
    os.makedirs(yol, exist_ok=True)
    return yol


class VideoIndirici(App):
    def build(self):
        self.title = "Video İndirici"
        kok = BoxLayout(orientation="vertical", padding=20, spacing=14)

        kok.add_widget(Label(text="Video İndirici", font_size="26sp",
                             size_hint_y=None, height=60))

        self.url = TextInput(hint_text="Video bağlantısını yapıştırın",
                             multiline=False, size_hint_y=None, height=100,
                             font_size="16sp")
        kok.add_widget(self.url)

        self.tur = Spinner(text="Video (MP4)",
                           values=("Video (MP4)", "Sadece ses (M4A)"),
                           size_hint_y=None, height=100)
        kok.add_widget(self.tur)

        self.bar = ProgressBar(max=100, value=0, size_hint_y=None, height=30)
        kok.add_widget(self.bar)

        self.btn = Button(text="İndir", size_hint_y=None, height=120,
                          font_size="20sp")
        self.btn.bind(on_release=self.baslat)
        kok.add_widget(self.btn)

        self.durum = Label(text="Hazır", halign="center")
        self.durum.bind(size=lambda w, s: setattr(w, "text_size", (s[0], None)))
        kok.add_widget(self.durum)
        return kok

    def on_start(self):
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([Permission.WRITE_EXTERNAL_STORAGE,
                                 Permission.READ_EXTERNAL_STORAGE])
        except ImportError:
            pass

    def ui(self, fn):
        Clock.schedule_once(lambda dt: fn(), 0)

    def baslat(self, *_):
        link = self.url.text.strip()
        if not link:
            self.durum.text = "Lütfen bir bağlantı girin."
            return
        self.btn.disabled = True
        self.bar.value = 0
        self.durum.text = "Başlıyor…"
        threading.Thread(target=self.indir, args=(link,), daemon=True).start()

    def ilerleme(self, d):
        if d.get("status") == "downloading":
            toplam = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if toplam:
                yuzde = d.get("downloaded_bytes", 0) * 100 / toplam
                self.ui(lambda: setattr(self.bar, "value", yuzde))
                self.ui(lambda: setattr(self.durum, "text",
                                        f"İndiriliyor… %{yuzde:.1f}"))
        elif d.get("status") == "finished":
            self.ui(lambda: setattr(self.durum, "text", "Kaydediliyor…"))

    def indir(self, link):
        gunluk = SessizGunluk()
        secenekler = {
            "outtmpl": os.path.join(indirme_klasoru(), "%(title)s.%(ext)s"),
            "progress_hooks": [self.ilerleme],
            "noplaylist": True,
            "restrictfilenames": True,
            "logger": gunluk,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
        }
        if self.tur.text.startswith("Sadece ses"):
            secenekler["format"] = "bestaudio[ext=m4a]/bestaudio"
        else:
            secenekler["format"] = "best[ext=mp4]/best"
        try:
            with yt_dlp.YoutubeDL(secenekler) as ydl:
                ydl.download([link])
            self.ui(lambda: setattr(self.durum, "text",
                                    "Tamamlandı ✔ İndirilenler klasörüne kaydedildi"))
            self.ui(lambda: setattr(self.bar, "value", 100))
        except Exception as e:
            satirlar = traceback.format_exc().strip().splitlines()
            konum = " | ".join(s.strip() for s in satirlar[-4:-1])[-220:]
            hata = (gunluk.son_hata or str(e))[:200]
            mesaj = f"Hata: {hata}\n{konum}"
            self.ui(lambda: setattr(self.durum, "text", mesaj))
        finally:
            self.ui(lambda: setattr(self.btn, "disabled", False))


if __name__ == "__main__":
    VideoIndirici().run()
