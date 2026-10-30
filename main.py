import os
import threading

try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
except ImportError:
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
        if d["status"] == "downloading":
            toplam = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if toplam:
                yuzde = d["downloaded_bytes"] * 100 / toplam
                self.ui(lambda: setattr(self.bar, "value", yuzde))
                self.ui(lambda: setattr(self.durum, "text",
                                        f"İndiriliyor… %{yuzde:.1f}"))
        elif d["status"] == "finished":
            self.ui(lambda: setattr(self.durum, "text", "Kaydediliyor…"))

    def indir(self, link):
        secenekler = {
            "outtmpl": os.path.join(indirme_klasoru(), "%(title)s.%(ext)s"),
            "progress_hooks": [self.ilerleme],
            "noplaylist": True,
            "restrictfilenames": True,
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
            hata = str(e)[:200]
            self.ui(lambda: setattr(self.durum, "text", f"Hata: {hata}"))
        finally:
            self.ui(lambda: setattr(self.btn, "disabled", False))


if __name__ == "__main__":
    VideoIndirici().run()
