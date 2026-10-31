"""YouTube tarzı parçalı (fragmented) MP4 dosyalarını birleştirir.

Bir dosya yalnızca görüntü, diğeri yalnızca ses içerir. FFmpeg gerekmez:
kutular okunur, tek bir moov altında iki iz tanımlanır ve parçalar
(moof+mdat) zaman sırasına göre dizilir. Veri yeniden kodlanmaz.
"""
import struct

KOPYA_BOYUT = 1024 * 1024


class MuxHatasi(Exception):
    pass


# ---------- kutu yardimcilari ----------

def _kutu(tip, icerik):
    return struct.pack(">I4s", 8 + len(icerik), tip) + bytes(icerik)


def _cocuklar(veri):
    """bytes icindeki kutulari [(tip, icerik)] olarak dondurur."""
    cikti = []
    pos = 0
    n = len(veri)
    while pos + 8 <= n:
        boyut, tip = struct.unpack(">I4s", veri[pos:pos + 8])
        baslik = 8
        if boyut == 1:
            if pos + 16 > n:
                break
            boyut = struct.unpack(">Q", veri[pos + 8:pos + 16])[0]
            baslik = 16
        elif boyut == 0:
            boyut = n - pos
        if boyut < baslik:
            break
        cikti.append((tip, bytes(veri[pos + baslik:pos + boyut])))
        pos += boyut
    return cikti


def _birlestir(cocuklar):
    return b"".join(_kutu(t, i) for t, i in cocuklar)


def _ust_kutular(f, dosya_boyutu):
    """Dosyanin ust duzey kutulari: (ofset, boyut, tip, baslik_boyu)."""
    pos = 0
    while pos + 8 <= dosya_boyutu:
        f.seek(pos)
        b = f.read(16)
        if len(b) < 8:
            return
        boyut, tip = struct.unpack(">I4s", b[:8])
        baslik = 8
        if boyut == 1:
            if len(b) < 16:
                return
            boyut = struct.unpack(">Q", b[8:16])[0]
            baslik = 16
        elif boyut == 0:
            boyut = dosya_boyutu - pos
        if boyut < baslik:
            return
        if pos + boyut > dosya_boyutu:
            boyut = dosya_boyutu - pos  # kesik son kutu
        yield pos, boyut, tip, baslik
        pos += boyut


# ---------- moov isleme ----------

def _tkhd_id(payload):
    surum = payload[0]
    ofs = 4 + (16 if surum == 1 else 8)
    return struct.unpack(">I", payload[ofs:ofs + 4])[0], ofs


def _tkhd_id_yaz(payload, yeni):
    _, ofs = _tkhd_id(payload)
    return payload[:ofs] + struct.pack(">I", yeni) + payload[ofs + 4:]


def _mdhd_zaman_olcegi(trak_payload):
    for tip, ic in _cocuklar(trak_payload):
        if tip == b"mdia":
            for t2, i2 in _cocuklar(ic):
                if t2 == b"mdhd":
                    ofs = 20 if i2[0] == 1 else 12
                    return struct.unpack(">I", i2[ofs:ofs + 4])[0]
    raise MuxHatasi("mdhd bulunamadi")


def _trak_bul(moov_payload):
    cocuklar = _cocuklar(moov_payload)
    trakler = [(t, i) for t, i in cocuklar if t == b"trak"]
    if len(trakler) != 1:
        raise MuxHatasi("dosyada tek iz beklenirdi")
    return cocuklar, trakler[0][1]


def _mvhd_yama(payload, sonraki_iz, sure_sn):
    p = bytearray(payload)
    surum = p[0]
    if surum == 1:
        zo, so, no = 20, 24, 108
    else:
        zo, so, no = 12, 16, 96
    olcek = struct.unpack(">I", p[zo:zo + 4])[0]
    if sure_sn:
        sure = int(sure_sn * olcek)
        if surum == 1:
            p[so:so + 8] = struct.pack(">Q", sure)
        else:
            p[so:so + 4] = struct.pack(">I", min(sure, 0xFFFFFFFF))
    p[no:no + 4] = struct.pack(">I", sonraki_iz)
    return bytes(p), olcek


def _moov_birlestir(v_moov, a_moov, sure_sn):
    v_coc, v_trak = _trak_bul(v_moov)
    a_coc, a_trak = _trak_bul(a_moov)

    v_id = None
    for t, i in _cocuklar(v_trak):
        if t == b"tkhd":
            v_id, _ = _tkhd_id(i)
    a_eski = None
    for t, i in _cocuklar(a_trak):
        if t == b"tkhd":
            a_eski, _ = _tkhd_id(i)
    if v_id is None or a_eski is None:
        raise MuxHatasi("tkhd bulunamadi")
    a_id = v_id + 1

    a_trak_yeni = _birlestir([
        (t, _tkhd_id_yaz(i, a_id) if t == b"tkhd" else i)
        for t, i in _cocuklar(a_trak)
    ])

    # mvex: video trex + ses trex
    v_mvex = next((i for t, i in v_coc if t == b"mvex"), None)
    a_mvex = next((i for t, i in a_coc if t == b"mvex"), None)
    if v_mvex is None or a_mvex is None:
        raise MuxHatasi("dosya parcali degil (mvex yok)")
    a_trex = next((i for t, i in _cocuklar(a_mvex) if t == b"trex"), None)
    if a_trex is None:
        raise MuxHatasi("trex bulunamadi")
    a_trex = a_trex[:4] + struct.pack(">I", a_id) + a_trex[8:]

    olcek_v = None
    for t, i in v_coc:
        if t == b"mvhd":
            olcek_v = struct.unpack(">I", i[(20 if i[0] == 1 else 12):(24 if i[0] == 1 else 16)])[0]

    yeni_mvex = []
    if sure_sn and olcek_v:
        mehd = bytes([1, 0, 0, 0]) + struct.pack(">Q", int(sure_sn * olcek_v))
        yeni_mvex.append((b"mehd", mehd))
    for t, i in _cocuklar(v_mvex):
        if t != b"mehd":
            yeni_mvex.append((t, i))
    yeni_mvex.append((b"trex", a_trex))

    yeni = []
    for t, i in v_coc:
        if t == b"mvhd":
            yama, _ = _mvhd_yama(i, a_id + 1, sure_sn)
            yeni.append((t, yama))
        elif t == b"trak":
            yeni.append((t, i))
            yeni.append((b"trak", a_trak_yeni))
        elif t == b"mvex":
            yeni.append((b"mvex", _birlestir(yeni_mvex)))
        else:
            yeni.append((t, i))
    return _kutu(b"moov", _birlestir(yeni)), v_id, a_id, a_eski


# ---------- parcalar (moof + mdat) ----------

def _moof_yama(moof_tam, yeni_id, zaman_olcegi):
    """moof bytes'ini (basligiyla) alir; iz numarasini degistirir.
    (basla_sn, bytearray) dondurur. Sira numarasi sonra yazilir."""
    b = bytearray(moof_tam)
    baslik = 8
    if struct.unpack(">I", b[:4])[0] == 1:
        baslik = 16
    pos = baslik
    mfhd_ofs = None
    zaman = None
    traf_sayisi = 0
    n = len(b)
    while pos + 8 <= n:
        boyut, tip = struct.unpack(">I4s", bytes(b[pos:pos + 8]))
        if boyut < 8:
            break
        if tip == b"mfhd":
            mfhd_ofs = pos + 8 + 4
        elif tip == b"traf":
            traf_sayisi += 1
            p2 = pos + 8
            son = pos + boyut
            while p2 + 8 <= son:
                bo2, ti2 = struct.unpack(">I4s", bytes(b[p2:p2 + 8]))
                if bo2 < 8:
                    break
                if ti2 == b"tfhd":
                    bayrak = int.from_bytes(b[p2 + 9:p2 + 12], "big")
                    if bayrak & 0x1:
                        raise MuxHatasi("base-data-offset desteklenmiyor")
                    b[p2 + 12:p2 + 16] = struct.pack(">I", yeni_id)
                elif ti2 == b"tfdt":
                    if b[p2 + 8] == 1:
                        zaman = struct.unpack(">Q", bytes(b[p2 + 12:p2 + 20]))[0]
                    else:
                        zaman = struct.unpack(">I", bytes(b[p2 + 12:p2 + 16]))[0]
                p2 += bo2
        pos += boyut
    if traf_sayisi != 1:
        raise MuxHatasi("parcada tek traf beklenirdi")
    basla = (zaman / zaman_olcegi) if zaman is not None else None
    return basla, b, mfhd_ofs


def _parcalari_oku(yol, yeni_id, zaman_olcegi):
    """[(sure, moof_bytearray, mfhd_ofs, mdat_ofs, mdat_boyut)] dondurur."""
    import os
    parcalar = []
    boyut_toplam = os.path.getsize(yol)
    with open(yol, "rb") as f:
        bekleyen = None
        for pos, boyut, tip, baslik in _ust_kutular(f, boyut_toplam):
            if tip == b"moof":
                f.seek(pos)
                bekleyen = f.read(boyut)
            elif tip == b"mdat":
                if bekleyen is None:
                    raise MuxHatasi("dosya parcali degil (moof yok)")
                basla, moof, mfhd = _moof_yama(bekleyen, yeni_id, zaman_olcegi)
                parcalar.append([basla, moof, mfhd, pos, boyut])
                bekleyen = None
    if not parcalar:
        raise MuxHatasi("parca bulunamadi")
    return parcalar


def _zamanlari_tamamla(parcalar):
    """tfdt olmayan parcalara oransal zaman ver."""
    n = len(parcalar)
    if all(p[0] is not None for p in parcalar):
        return
    for i, p in enumerate(parcalar):
        p[0] = float(i)  # kaba siralama: sira numarasi


# ---------- ana islev ----------

def birlestir(video_yolu, ses_yolu, cikis_yolu, sure_sn=None, ilerleme=None):
    import os

    def oku_ust(yol):
        ftyp = None
        moov = None
        boyut_toplam = os.path.getsize(yol)
        with open(yol, "rb") as f:
            for pos, boyut, tip, baslik in _ust_kutular(f, boyut_toplam):
                if tip == b"ftyp" and ftyp is None:
                    f.seek(pos)
                    ftyp = f.read(boyut)
                elif tip == b"moov" and moov is None:
                    f.seek(pos + baslik)
                    moov = f.read(boyut - baslik)
        if moov is None:
            raise MuxHatasi("moov bulunamadi")
        return ftyp, moov

    v_ftyp, v_moov = oku_ust(video_yolu)
    _, a_moov = oku_ust(ses_yolu)

    moov, v_id, a_id, a_eski = _moov_birlestir(v_moov, a_moov, sure_sn)

    _, v_trak = _trak_bul(v_moov)
    _, a_trak = _trak_bul(a_moov)
    v_olcek = _mdhd_zaman_olcegi(v_trak)
    a_olcek = _mdhd_zaman_olcegi(a_trak)

    v_parca = _parcalari_oku(video_yolu, v_id, v_olcek)
    a_parca = _parcalari_oku(ses_yolu, a_id, a_olcek)
    _zamanlari_tamamla(v_parca)
    _zamanlari_tamamla(a_parca)

    liste = [(p[0], 0, i, p, video_yolu) for i, p in enumerate(v_parca)]
    liste += [(p[0], 1, i, p, ses_yolu) for i, p in enumerate(a_parca)]
    liste.sort(key=lambda x: (x[0], x[1], x[2]))

    toplam = sum(p[4] for _, _, _, p, _ in liste) or 1
    yazilan = 0
    ftyp = v_ftyp or _kutu(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso6dashmp41")

    with open(cikis_yolu, "wb") as out:
        out.write(ftyp)
        out.write(moov)
        kaynaklar = {}
        try:
            for sira, (_, _, _, p, yol) in enumerate(liste, 1):
                _, moof, mfhd, mdat_ofs, mdat_boyut = p
                if mfhd is not None:
                    moof[mfhd:mfhd + 4] = struct.pack(">I", sira)
                out.write(bytes(moof))
                f = kaynaklar.get(yol)
                if f is None:
                    f = kaynaklar[yol] = open(yol, "rb")
                f.seek(mdat_ofs)
                kalan = mdat_boyut
                while kalan > 0:
                    blok = f.read(min(KOPYA_BOYUT, kalan))
                    if not blok:
                        raise MuxHatasi("kaynak dosya beklenenden kisa")
                    out.write(blok)
                    kalan -= len(blok)
                yazilan += mdat_boyut
                if ilerleme and sira % 20 == 0:
                    ilerleme(yazilan / toplam)
        finally:
            for f in kaynaklar.values():
                f.close()
    if ilerleme:
        ilerleme(1.0)
