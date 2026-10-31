import os
import re
import shutil
import ssl
import sys
import threading
import time
import traceback
import urllib.request
from urllib.parse import urlparse


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
    certifi = None

import yt_dlp
from yt_dlp.utils import sanitize_filename
import mp4muxer
from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import Image
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


def ekran_acik(ac):
    """Indirme sirasinda ekranin kapanip agin kesilmesini onler (yalniz Android)."""
    try:
        from android.runnable import run_on_ui_thread
        from jnius import autoclass

        @run_on_ui_thread
        def _yap():
            etkinlik = autoclass("org.kivy.android.PythonActivity").mActivity
            bayrak = autoclass("android.view.WindowManager$LayoutParams").FLAG_KEEP_SCREEN_ON
            pencere = etkinlik.getWindow()
            if ac:
                pencere.addFlags(bayrak)
            else:
                pencere.clearFlags(bayrak)

        _yap()
    except Exception:
        pass


def ag_hatasi(metin):
    m = str(metin).lower()
    return any(x in m for x in ("got error", "fail", "timed out", "connection",
                                "errno", "reset", "unreachable", "incomplete",
                                "temporar", "resolve", "ssl"))


def benzersiz_yol(yol):
    if not os.path.exists(yol):
        return yol
    govde, uzanti = os.path.splitext(yol)
    n = 2
    while os.path.exists(f"{govde} ({n}){uzanti}"):
        n += 1
    return f"{govde} ({n}){uzanti}"


def indirilen_dosya(bilgi, ydl):
    try:
        return bilgi["requested_downloads"][0]["filepath"]
    except Exception:
        return ydl.prepare_filename(bilgi)


def kisa_hata(metin, uzunluk=70):
    metin = str(metin).replace("ERROR: ", "")
    if "]" in metin[:40]:
        metin = metin.split("]", 1)[1].strip()
    return metin[:uzunluk]


def sure_yazisi(saniye):
    try:
        saniye = int(saniye)
    except Exception:
        return ""
    s, sn = divmod(saniye, 60)
    sa, s = divmod(s, 60)
    if sa:
        return f"{sa}:{s:02d}:{sn:02d}"
    return f"{s}:{sn:02d}"


def kapak_adresi(bilgi):
    uzantilar = (".jpg", ".jpeg", ".png")
    adaylar = []
    for t in bilgi.get("thumbnails") or []:
        adres = t.get("url") or ""
        if urlparse(adres).path.lower().endswith(uzantilar):
            adaylar.append(adres)
    if adaylar:
        return adaylar[-1]
    tek = bilgi.get("thumbnail") or ""
    if urlparse(tek).path.lower().endswith(uzantilar):
        return tek
    if str(bilgi.get("extractor_key", "")).lower().startswith("youtube") and bilgi.get("id"):
        return f"https://i.ytimg.com/vi/{bilgi['id']}/hqdefault.jpg"
    return ""


def kapak_indir(adres, hedef):
    if certifi is not None:
        baglam = ssl.create_default_context(cafile=certifi.where())
    else:
        baglam = ssl.create_default_context()
    istek = urllib.request.Request(adres, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(istek, timeout=15, context=baglam) as r:
        veri = r.read(3_000_000)
    with open(hedef, "wb") as f:
        f.write(veri)


class VideoIndirici(App):
    def build(self):
        self.title = "Video İndirici"
        self.onizleme_no = 0
        self.faz = (0, 100, "")
        self.bekleyen = None

        kok = BoxLayout(orientation="vertical", padding=20, spacing=12)

        kok.add_widget(Label(text="Video İndirici", font_size="26sp",
                             size_hint_y=None, height=60))

        self.url = TextInput(hint_text="Video bağlantısını yapıştırın",
                             multiline=False, size_hint_y=None, height=100,
                             font_size="16sp")
        self.url.bind(text=self.link_degisti)
        kok.add_widget(self.url)

        self.kapak = Image(size_hint_y=None, height=220, fit_mode="contain")
        kok.add_widget(self.kapak)

        self.baslik = Label(text="", halign="center", valign="middle",
                            size_hint_y=None, height=70, font_size="15sp",
                            max_lines=2, shorten=True, shorten_from="right")
        self.baslik.bind(size=lambda w, s: setattr(w, "text_size", (s[0], s[1])))
        kok.add_widget(self.baslik)

        self.alt = Label(text="", halign="center", size_hint_y=None, height=30,
                         font_size="13sp", color=(0.7, 0.7, 0.7, 1))
        self.alt.bind(size=lambda w, s: setattr(w, "text_size", (s[0], None)))
        kok.add_widget(self.alt)

        self.tur = Spinner(text="Video 720p",
                           values=("Video 1080p", "Video 720p", "Video 480p",
                                   "Video 360p", "Sadece ses (M4A)"),
                           size_hint_y=None, height=100)
        kok.add_widget(self.tur)

        self.bar = ProgressBar(max=100, value=0, size_hint_y=None, height=30)
        kok.add_widget(self.bar)

        self.btn = Button(text="İndir", size_hint_y=None, height=120,
                          font_size="20sp")
        self.btn.bind(on_release=self.baslat)
        kok.add_widget(self.btn)

        self.durum = Label(text="Hazır", halign="center", font_size="12sp")
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

    def link_degisti(self, _w, metin):
        if self.bekleyen is not None:
            self.bekleyen.cancel()
            self.bekleyen = None
        self.onizleme_no += 1
        metin = metin.strip()
        if not metin.lower().startswith("http"):
            self.kapak.source = ""
            self.baslik.text = ""
            self.alt.text = ""
            return
        no = self.onizleme_no
        self.bekleyen = Clock.schedule_once(
            lambda dt: self.onizleme_baslat(metin, no), 0.8)

    def onizleme_baslat(self, link, no):
        self.baslik.text = "Önizleme yükleniyor…"
        self.alt.text = ""
        self.kapak.source = ""
        threading.Thread(target=self.onizleme_al, args=(link, no),
                         daemon=True).start()

    def onizleme_al(self, link, no):
        try:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "logger": SessizGunluk(),
                "noplaylist": True,
                "skip_download": True,
                "ignore_no_formats_error": True,
                "socket_timeout": 15,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                bilgi = ydl.extract_info(link, download=False)
            if not isinstance(bilgi, dict):
                raise ValueError("bilgi yok")

            baslik = bilgi.get("title") or "Başlık yok"
            sure = sure_yazisi(bilgi.get("duration"))
            kanal = bilgi.get("uploader") or ""
            alt = " · ".join(x for x in (kanal, sure) if x)

            yol = ""
            adres = kapak_adresi(bilgi)
            if adres:
                try:
                    yol = os.path.join(self.user_data_dir, f"kapak_{no}.jpg")
                    kapak_indir(adres, yol)
                except Exception:
                    yol = ""

            def goster():
                if no != self.onizleme_no:
                    return
                self.baslik.text = baslik
                self.alt.text = alt
                if yol:
                    self.kapak.source = yol
                    self.kapak.reload()

            self.ui(goster)
        except Exception:
            def hata():
                if no == self.onizleme_no:
                    self.baslik.text = "Önizleme alınamadı"
                    self.kapak.source = ""
            self.ui(hata)

    def baslat(self, *_):
        link = self.url.text.strip()
        if not link:
            self.durum.text = "Lütfen bir bağlantı girin."
            return
        self.btn.disabled = True
        self.bar.value = 0
        self.durum.text = "Başlıyor… (indirme bitene kadar uygulamadan çıkmayın)"
        ekran_acik(True)
        threading.Thread(target=self.indir, args=(link,), daemon=True).start()

    def ilerleme(self, d):
        b, e, ad = self.faz
        if d.get("status") == "downloading":
            toplam = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if toplam:
                p = d.get("downloaded_bytes", 0) * 100 / toplam
                genel = b + (e - b) * p / 100
                etiket = f"{ad} indiriliyor… %{p:.0f}" if ad else f"İndiriliyor… %{p:.1f}"
                self.ui(lambda: setattr(self.bar, "value", genel))
                self.ui(lambda: setattr(self.durum, "text", etiket))
        elif d.get("status") == "finished" and not ad:
            self.ui(lambda: setattr(self.durum, "text", "Kaydediliyor…"))

    def yukseklik(self):
        m = re.search(r"(\d{3,4})p", self.tur.text)
        return int(m.group(1)) if m else 720

    def secenekler(self, gunluk, istemci, sadece_liste=False):
        ses = self.tur.text.startswith("Sadece ses")
        h = self.yukseklik()
        o = {
            "outtmpl": os.path.join(indirme_klasoru(), "%(title)s.%(ext)s"),
            "progress_hooks": [self.ilerleme],
            "noplaylist": True,
            "restrictfilenames": True,
            "logger": gunluk,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "socket_timeout": 30,
            "retries": 20,
            "fragment_retries": 20,
            "retry_sleep_functions": {
                "http": lambda n: min(2 * n, 15),
                "fragment": lambda n: min(2 * n, 15),
            },
            "format": ("bestaudio[ext=m4a]/bestaudio" if ses else
                       f"best[height<={h}][ext=mp4]/best[height<={h}]/best[ext=mp4]/best"),
        }
        if getattr(self, "ipv4", False):
            o["source_address"] = "0.0.0.0"
        if istemci:
            o["extractor_args"] = {"youtube": {"player_client": [istemci]}}
        if sadece_liste:
            o["skip_download"] = True
            o["ignore_no_formats_error"] = True
        return o

    def format_ozeti(self, link, istemciler):
        parcalar = []
        for istemci in istemciler:
            ad = istemci or "varsayilan"
            try:
                with yt_dlp.YoutubeDL(self.secenekler(SessizGunluk(), istemci, True)) as ydl:
                    bilgi = ydl.extract_info(link, download=False)
                ortak = vid = ses = 0
                ortak_bilgi = ""
                mp4_vid = []
                for f in bilgi.get("formats") or []:
                    v = f.get("vcodec") not in (None, "none")
                    a = f.get("acodec") not in (None, "none")
                    if v and a:
                        ortak += 1
                        ortak_bilgi = f"{f.get('format_id')}/{f.get('ext')}/{f.get('height')}p/{f.get('protocol')}"
                    elif v:
                        vid += 1
                        if f.get("ext") == "mp4":
                            mp4_vid.append(f.get("height") or 0)
                    elif a:
                        ses += 1
                ek = f" [{ortak_bilgi}]" if ortak_bilgi else ""
                if mp4_vid:
                    ek += f" mp4:{min(mp4_vid)}-{max(mp4_vid)}p"
                parcalar.append(f"{ad}: {ortak}/{vid}/{ses}{ek}")
            except Exception:
                parcalar.append(f"{ad}: yok")
        return "\n".join(parcalar)

    def parcali_indir(self, link):
        """Goruntu ve sesi ayri indirip FFmpeg olmadan birlestirir.
        Gecici dosyalar basarisizlikta korunur; yeniden denemede kaldigi yerden surer."""
        h = self.yukseklik()
        gecici = os.path.join(self.user_data_dir, "gecici")
        os.makedirs(gecici, exist_ok=True)
        simdi = time.time()
        for dosya in os.listdir(gecici):
            yol = os.path.join(gecici, dosya)
            try:
                if simdi - os.path.getmtime(yol) > 24 * 3600:
                    os.remove(yol)
            except OSError:
                pass

        gunluk = SessizGunluk()
        v_sec = self.secenekler(gunluk, None)
        v_sec["format"] = (f"bestvideo[height<={h}][ext=mp4][vcodec^=avc1]/"
                           f"bestvideo[height<={h}][ext=mp4]/worstvideo[ext=mp4]")
        v_sec["outtmpl"] = os.path.join(gecici, f"v_{h}_%(id)s.%(ext)s")
        self.faz = (0, 78, "Görüntü")
        with yt_dlp.YoutubeDL(v_sec) as ydl:
            bilgi = ydl.extract_info(link, download=True)
            vyol = indirilen_dosya(bilgi, ydl)

        a_sec = self.secenekler(gunluk, None)
        a_sec["format"] = "bestaudio[ext=m4a]"
        a_sec["outtmpl"] = os.path.join(gecici, "a_%(id)s.%(ext)s")
        self.faz = (78, 92, "Ses")
        with yt_dlp.YoutubeDL(a_sec) as ydl:
            abilgi = ydl.extract_info(link, download=True)
            ayol = indirilen_dosya(abilgi, ydl)

        ad = sanitize_filename(bilgi.get("title") or "video").strip(" .")[:80] or "video"
        klasor = indirme_klasoru()
        cikis = benzersiz_yol(os.path.join(klasor, ad + ".mp4"))

        self.ui(lambda: setattr(self.durum, "text", "Birleştiriliyor…"))

        def birlesme(oran):
            v = 92 + 8 * oran
            self.ui(lambda: setattr(self.bar, "value", v))

        try:
            mp4muxer.birlestir(vyol, ayol, cikis, bilgi.get("duration"), birlesme)
        except Exception as e:
            try:
                os.remove(cikis)
            except OSError:
                pass
            v_son = benzersiz_yol(os.path.join(klasor, ad + " (görüntü).mp4"))
            a_son = benzersiz_yol(os.path.join(klasor, ad + " (ses).m4a"))
            shutil.move(vyol, v_son)
            shutil.move(ayol, a_son)
            mesaj = ("Birleştirilemedi (" + kisa_hata(e, 60) + "). "
                     "Görüntü ve ses ayrı dosyalar olarak İndirilenler'e kaydedildi.")
            self.ui(lambda: setattr(self.durum, "text", mesaj))
            return True

        for dosya in (vyol, ayol):
            try:
                os.remove(dosya)
            except OSError:
                pass
        etiket = (f"Tamamlandı ✔ {h}p'ye kadar, görüntü+ses birleştirildi.\n"
                  f"İndirilenler: {os.path.basename(cikis)}")
        self.ui(lambda: setattr(self.durum, "text", etiket))
        self.ui(lambda: setattr(self.bar, "value", 100))
        return True

    def indir(self, link):
        ses = self.tur.text.startswith("Sadece ses")
        youtube = any(x in link.lower() for x in ("youtube.com", "youtu.be"))
        istemciler = [None, "android_vr", "web_safari", "ios", "tv", "mweb"] if youtube else [None]
        hatalar = []
        self.ipv4 = False
        try:
            if youtube and not ses:
                for deneme in range(1, 4):
                    self.ipv4 = deneme >= 2
                    try:
                        self.parcali_indir(link)
                        return
                    except Exception as e:
                        metin = str(e)
                        hatalar.append(f"birlestirme{deneme}{' (ipv4)' if self.ipv4 else ''}: "
                                       + kisa_hata(metin, 140))
                        self.faz = (0, 100, "")
                        if deneme < 3 and ag_hatasi(metin):
                            self.ui(lambda d=deneme: setattr(
                                self.durum, "text",
                                f"Bağlantı koptu, kaldığı yerden devam ediliyor ({d + 1}/3)…"))
                            time.sleep(3)
                        else:
                            break
                self.ipv4 = False

            for sira, istemci in enumerate(istemciler, 1):
                gunluk = SessizGunluk()
                if len(istemciler) > 1:
                    self.ui(lambda s=sira: setattr(
                        self.durum, "text", f"Deneniyor… ({s}/{len(istemciler)})"))
                try:
                    with yt_dlp.YoutubeDL(self.secenekler(gunluk, istemci)) as ydl:
                        ydl.download([link])
                    ek = f" (yöntem: {istemci or 'varsayılan'})" if youtube else ""
                    self.ui(lambda ek=ek: setattr(
                        self.durum, "text",
                        "Tamamlandı ✔ İndirilenler klasörüne kaydedildi" + ek))
                    self.ui(lambda: setattr(self.bar, "value", 100))
                    return
                except Exception as e:
                    hatalar.append(f"{istemci or 'varsayilan'}: "
                                   + kisa_hata(gunluk.son_hata or e))

            mesaj = "Hata. Denemeler:\n" + "\n".join(hatalar)
            if youtube:
                self.ui(lambda: setattr(self.durum, "text", mesaj + "\nFormatlar hazırlanıyor…"))
                ozet = self.format_ozeti(link, istemciler[:2])
                mesaj += "\n\nFormatlar (ortak/video/ses):\n" + ozet
            self.ui(lambda: setattr(self.durum, "text", mesaj))
        except Exception as e:
            satirlar = traceback.format_exc().strip().splitlines()
            konum = " | ".join(x.strip() for x in satirlar[-4:-1])[-220:]
            mesaj = f"Hata: {str(e)[:200]}\n{konum}"
            self.ui(lambda: setattr(self.durum, "text", mesaj))
        finally:
            self.faz = (0, 100, "")
            ekran_acik(False)
            self.ui(lambda: setattr(self.btn, "disabled", False))


if __name__ == "__main__":
    VideoIndirici().run()
