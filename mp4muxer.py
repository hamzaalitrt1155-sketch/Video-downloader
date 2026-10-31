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


def _tkhd_sure_ofs(payload):
    # fullbox(4) + olusturma + degistirme + iz_no(4) + ayrilmis(4)
    return 4 + (16 if payload[0] == 1 else 8) + 4 + 4


def _tkhd_sure_oku(payload):
    ofs = _tkhd_sure_ofs(payload)
    if payload[0] == 1:
        return struct.unpack(">Q", payload[ofs:ofs + 8])[0]
    return struct.unpack(">I", payload[ofs:ofs + 4])[0]


def _tkhd_sure_yaz(payload, tik):
    ofs = _tkhd_sure_ofs(payload)
    p = bytearray(payload)
    if payload[0] == 1:
        p[ofs:ofs + 8] = struct.pack(">Q", tik)
    else:
        p[ofs:ofs + 4] = struct.pack(">I", min(tik, 0xFFFFFFFF))
    return bytes(p)


def _edts_olcekle(edts_payload, oran):
    """elst girdilerindeki segment suresini film zaman olcegine gore yeniden olcekler."""
    yeni = []
    for t, i in _cocuklar(edts_payload):
        if t == b"elst" and len(i) >= 8:
            surum = i[0]
            sayi = struct.unpack(">I", i[4:8])[0]
            p = bytearray(i)
            ofs = 8
            for _ in range(sayi):
                if surum == 1:
                    sd = struct.unpack(">Q", p[ofs:ofs + 8])[0]
                    p[ofs:ofs + 8] = struct.pack(">Q", int(sd * oran))
                    ofs += 20
                else:
                    sd = struct.unpack(">I", p[ofs:ofs + 4])[0]
                    p[ofs:ofs + 4] = struct.pack(">I", min(int(sd * oran), 0xFFFFFFFF))
                    ofs += 12
            i = bytes(p)
        yeni.append((t, i))
    return _birlestir(yeni)


def _film_olcegi(cocuklar):
    for t, i in cocuklar:
        if t == b"mvhd":
            ofs = 20 if i[0] == 1 else 12
            return struct.unpack(">I", i[ofs:ofs + 4])[0]
    raise MuxHatasi("mvhd bulunamadi")



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

    # Ses dosyasinin film zaman olcegi video dosyasininkinden farkli olabilir.
    # tkhd suresi ve elst segmentleri film olcegiyle yazildigi icin yeniden olceklenir
    # (yapilmazsa oynatici sureyi katlayarak gosterir).
    v_film = _film_olcegi(v_coc)
    a_film = _film_olcegi(a_coc)
    oran = v_film / a_film if a_film else 1.0

    yeni_a_cocuk = []
    for t, i in _cocuklar(a_trak):
        if t == b"tkhd":
            i = _tkhd_id_yaz(i, a_id)
            if sure_sn:
                tik = int(sure_sn * v_film)
            else:
                tik = int(_tkhd_sure_oku(i) * oran)
            i = _tkhd_sure_yaz(i, tik)
        elif t == b"edts":
            i = _edts_olcekle(i, oran)
        yeni_a_cocuk.append((t, i))
    a_trak_yeni = _birlestir(yeni_a_cocuk)

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

def birlestir_parcali(video_yolu, ses_yolu, cikis_yolu, sure_sn=None, ilerleme=None):
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


# =====================================================================
#  Klasik (parcali olmayan) MP4: ileri sarma her oynaticida calisir
# =====================================================================

def _u32(b, o):
    return struct.unpack(">I", b[o:o + 4])[0]


def _trex_varsayilan(moov_payload, iz_no):
    for t, i in _cocuklar(moov_payload):
        if t == b"mvex":
            for t2, i2 in _cocuklar(i):
                if t2 == b"trex" and _u32(i2, 4) == iz_no:
                    return {"sdi": _u32(i2, 8), "sure": _u32(i2, 12),
                            "boyut": _u32(i2, 16), "bayrak": _u32(i2, 20)}
    return {"sdi": 1, "sure": 0, "boyut": 0, "bayrak": 0}


def _moof_coz(moof, moof_ofs, mdat_veri_ofs, trex):
    """Bir moof'u cozer: (basla_tik, sdi, kosular) dondurur.
    kosular: [(veri_baslangic_mutlak, [(sure, boyut, sync, cto), ...]), ...]"""
    baslik = 16 if _u32(moof, 0) == 1 else 8
    pos = baslik
    n = len(moof)
    tfdt = None
    sdi = trex["sdi"]
    v_sure, v_boyut, v_bayrak = trex["sure"], trex["boyut"], trex["bayrak"]
    kosular = []
    onceki_son = mdat_veri_ofs
    traf_say = 0
    while pos + 8 <= n:
        boyut, tip = struct.unpack(">I4s", moof[pos:pos + 8])
        if boyut < 8:
            break
        if tip == b"traf":
            traf_say += 1
            p2 = pos + 8
            son = pos + boyut
            while p2 + 8 <= son:
                b2, t2 = struct.unpack(">I4s", moof[p2:p2 + 8])
                if b2 < 8:
                    break
                ic = moof[p2 + 8:p2 + b2]
                if t2 == b"tfhd":
                    bayrak = int.from_bytes(ic[1:4], "big")
                    if bayrak & 0x1:
                        raise MuxHatasi("base-data-offset desteklenmiyor")
                    o = 8
                    if bayrak & 0x2:
                        sdi = _u32(ic, o); o += 4
                    if bayrak & 0x8:
                        v_sure = _u32(ic, o); o += 4
                    if bayrak & 0x10:
                        v_boyut = _u32(ic, o); o += 4
                    if bayrak & 0x20:
                        v_bayrak = _u32(ic, o); o += 4
                elif t2 == b"tfdt":
                    if ic[0] == 1:
                        tfdt = struct.unpack(">Q", ic[4:12])[0]
                    else:
                        tfdt = _u32(ic, 4)
                elif t2 == b"trun":
                    surum = ic[0]
                    bayrak = int.from_bytes(ic[1:4], "big")
                    say = _u32(ic, 4)
                    o = 8
                    veri_ofs = None
                    if bayrak & 0x1:
                        veri_ofs = struct.unpack(">i", ic[o:o + 4])[0]; o += 4
                    ilk_bayrak = None
                    if bayrak & 0x4:
                        ilk_bayrak = _u32(ic, o); o += 4
                    alanlar = []
                    fmt = ">"
                    if bayrak & 0x100:
                        fmt += "I"; alanlar.append("sure")
                    if bayrak & 0x200:
                        fmt += "I"; alanlar.append("boyut")
                    if bayrak & 0x400:
                        fmt += "I"; alanlar.append("bayrak")
                    if bayrak & 0x800:
                        fmt += "i" if surum == 1 else "I"; alanlar.append("cto")
                    ornekler = []
                    if alanlar:
                        adim = struct.calcsize(fmt)
                        satirlar = struct.iter_unpack(fmt, ic[o:o + adim * say])
                    else:
                        satirlar = ((),) * say
                    for k, satir in enumerate(satirlar):
                        d = dict(zip(alanlar, satir))
                        sure = d.get("sure", v_sure)
                        bt = d.get("boyut", v_boyut)
                        bay = d.get("bayrak", v_bayrak)
                        if k == 0 and ilk_bayrak is not None:
                            bay = ilk_bayrak
                        ornekler.append((sure, bt, not (bay & 0x10000), d.get("cto", 0)))
                    if veri_ofs is not None:
                        baslangic = moof_ofs + veri_ofs
                    else:
                        baslangic = onceki_son
                    onceki_son = baslangic + sum(x[1] for x in ornekler)
                    kosular.append((baslangic, ornekler))
                p2 += b2
        pos += boyut
    if traf_say != 1:
        raise MuxHatasi("parcada tek traf beklenirdi")
    return tfdt, sdi, kosular


def _iz_parcalari(yol, iz_no, olcek, trex):
    """[{'t','sdi','kosular','toplam'}] dondurur (dosya sirasinda)."""
    import os
    parcalar = []
    toplam_boyut = os.path.getsize(yol)
    with open(yol, "rb") as f:
        bekleyen = None
        for pos, boyut, tip, baslik in _ust_kutular(f, toplam_boyut):
            if tip == b"moof":
                f.seek(pos)
                bekleyen = (pos, f.read(boyut))
            elif tip == b"mdat":
                if bekleyen is None:
                    raise MuxHatasi("dosya parcali degil (moof yok)")
                moof_pos, moof = bekleyen
                tfdt, sdi, kosular = _moof_coz(moof, moof_pos, pos + baslik, trex)
                toplam = sum(x[1] for _, o in kosular for x in o)
                for bas, o in kosular:
                    if bas < pos or bas + sum(x[1] for x in o) > toplam_boyut:
                        raise MuxHatasi("ornek verisi dosya disinda")
                parcalar.append({"t": (tfdt / olcek) if tfdt is not None else None,
                                 "tik": tfdt,
                                 "sdi": sdi, "kosular": kosular, "toplam": toplam})
                bekleyen = None
    if not parcalar:
        raise MuxHatasi("parca bulunamadi")
    if any(p["t"] is None for p in parcalar):
        for i, p in enumerate(parcalar):
            p["t"] = float(i)
    return parcalar


def _calistir(degerler):
    """[(deger, tekrar)] sirali calisma uzunluklari."""
    cikti = []
    for d in degerler:
        if cikti and cikti[-1][0] == d:
            cikti[-1][1] += 1
        else:
            cikti.append([d, 1])
    return cikti


def _stbl_kur(stsd, parcalar, ofsetler, taban, buyuk):
    durs, sizes, syncs, ctos = [], [], [], []
    chunk_say, chunk_sdi = [], []
    for p in parcalar:
        say = 0
        for _, ornekler in p["kosular"]:
            for sure, bt, sync, cto in ornekler:
                durs.append(sure); sizes.append(bt); syncs.append(sync); ctos.append(cto)
                say += 1
        chunk_say.append(say)
        chunk_sdi.append(p["sdi"])
    n = len(durs)

    stts_run = _calistir(durs)
    stts = _kutu(b"stts", b"\0\0\0\0" + struct.pack(">I", len(stts_run))
                 + b"".join(struct.pack(">II", c, d) for d, c in stts_run))

    kutular = [(b"stsd", stsd), (b"stts", stts[8:])]

    if any(c != 0 for c in ctos):
        surum = 1 if any(c < 0 for c in ctos) else 0
        run = _calistir(ctos)
        govde = bytes([surum, 0, 0, 0]) + struct.pack(">I", len(run))
        fmt = ">Ii" if surum == 1 else ">II"
        govde += b"".join(struct.pack(fmt, c, d) for d, c in run)
        kutular.append((b"ctts", govde))

    if not all(syncs):
        idx = [i + 1 for i, v in enumerate(syncs) if v]
        kutular.append((b"stss", b"\0\0\0\0" + struct.pack(">I", len(idx))
                        + struct.pack(f">{len(idx)}I", *idx)))

    chunk_run = _calistir(list(zip(chunk_say, chunk_sdi)))
    stsc = b"\0\0\0\0" + struct.pack(">I", len(chunk_run))
    ilk = 1
    for (say, sdi), tekrar in chunk_run:
        stsc += struct.pack(">III", ilk, say, sdi)
        ilk += tekrar
    kutular.append((b"stsc", stsc))

    kutular.append((b"stsz", b"\0\0\0\0" + struct.pack(">II", 0, n)
                    + struct.pack(f">{n}I", *sizes)))

    mutlak = [taban + o for o in ofsetler]
    if buyuk:
        kutular.append((b"co64", b"\0\0\0\0" + struct.pack(">I", len(mutlak))
                        + struct.pack(f">{len(mutlak)}Q", *mutlak)))
    else:
        kutular.append((b"stco", b"\0\0\0\0" + struct.pack(">I", len(mutlak))
                        + struct.pack(f">{len(mutlak)}I", *mutlak)))
    return _birlestir(kutular), sum(durs)


def _mdhd_sure_yaz(payload, sure):
    p = bytearray(payload)
    if payload[0] == 1:
        p[24:32] = struct.pack(">Q", sure)
    else:
        p[16:20] = struct.pack(">I", min(sure, 0xFFFFFFFF))
    return bytes(p)


def _edts_duzelt(edts_payload, oran, tam_tik):
    """Segment surelerini olcekler; 0 olanlara (parcali dosyalarda 'sona kadar') gercek sure yazar."""
    yeni = []
    for t, i in _cocuklar(edts_payload):
        if t == b"elst" and len(i) >= 8:
            surum = i[0]
            say = _u32(i, 4)
            p = bytearray(i)
            ofs = 8
            for _ in range(say):
                if surum == 1:
                    sd = struct.unpack(">Q", p[ofs:ofs + 8])[0]
                    sd = tam_tik if sd == 0 else int(round(sd * oran))
                    p[ofs:ofs + 8] = struct.pack(">Q", sd)
                    ofs += 20
                else:
                    sd = _u32(p, ofs)
                    sd = tam_tik if sd == 0 else int(round(sd * oran))
                    p[ofs:ofs + 4] = struct.pack(">I", min(sd, 0xFFFFFFFF))
                    ofs += 12
            i = bytes(p)
        yeni.append((t, i))
    return _birlestir(yeni)


def _edts_basa_bos(edts_payload, bos_tik):
    """Izin ilk parcasi sifirdan sonra basliyorsa basa bos bir elst girdisi ekler."""
    yeni = []
    for t, i in _cocuklar(edts_payload):
        if t == b"elst" and len(i) >= 8:
            surum = i[0]
            say = _u32(i, 4)
            if surum == 1:
                girdi = struct.pack(">QqHH", bos_tik, -1, 1, 0)
            else:
                girdi = struct.pack(">IiHH", min(bos_tik, 0xFFFFFFFF), -1, 1, 0)
            i = i[:4] + struct.pack(">I", say + 1) + girdi + i[8:]
        yeni.append((t, i))
    return _birlestir(yeni)


def _edts_yeni(bos_tik, medya_tik):
    elst = (bytes([0, 0, 0, 0]) + struct.pack(">I", 2)
            + struct.pack(">IiHH", min(bos_tik, 0xFFFFFFFF), -1, 1, 0)
            + struct.pack(">IiHH", min(medya_tik, 0xFFFFFFFF), 0, 1, 0))
    return _kutu(b"edts", _kutu(b"elst", elst))


def _trak_kur(trak_payload, yeni_id, parcalar, ofsetler, taban, buyuk,
              film_olcegi, edts_oran, baslangic_tik=0):
    mdhd_olcek = _mdhd_zaman_olcegi(trak_payload)
    # stsd'yi bul
    stsd = None
    for t, i in _cocuklar(trak_payload):
        if t == b"mdia":
            for t2, i2 in _cocuklar(i):
                if t2 == b"minf":
                    for t3, i3 in _cocuklar(i2):
                        if t3 == b"stbl":
                            for t4, i4 in _cocuklar(i3):
                                if t4 == b"stsd":
                                    stsd = i4
    if stsd is None:
        raise MuxHatasi("stsd bulunamadi")

    stbl, medya_sure = _stbl_kur(stsd, parcalar, ofsetler, taban, buyuk)
    medya_sn = medya_sure / mdhd_olcek
    medya_tik = int(round(medya_sn * film_olcegi))
    bos = int(round(baslangic_tik / mdhd_olcek * film_olcegi)) if baslangic_tik else 0
    tkhd_tik = medya_tik + bos
    iz_sn = medya_sn + (bos / film_olcegi if bos else 0.0)
    edts_var = False

    yeni = []
    for t, i in _cocuklar(trak_payload):
        if t == b"tkhd":
            i = _tkhd_sure_yaz(_tkhd_id_yaz(i, yeni_id), tkhd_tik)
        elif t == b"edts":
            i = _edts_duzelt(i, edts_oran, medya_tik)
            if bos:
                i = _edts_basa_bos(i, bos)
            edts_var = True
        elif t == b"mdia":
            m_yeni = []
            for t2, i2 in _cocuklar(i):
                if t2 == b"mdhd":
                    i2 = _mdhd_sure_yaz(i2, medya_sure)
                elif t2 == b"minf":
                    mi_yeni = []
                    for t3, i3 in _cocuklar(i2):
                        if t3 == b"stbl":
                            i3 = stbl
                        mi_yeni.append((t3, i3))
                    i2 = _birlestir(mi_yeni)
                m_yeni.append((t2, i2))
            i = _birlestir(m_yeni)
        yeni.append((t, i))
        if t == b"tkhd" and bos and not any(x == b"edts" for x, _ in _cocuklar(trak_payload)):
            yeni.append((b"edts", _edts_yeni(bos, medya_tik)[8:]))
    return _birlestir(yeni), iz_sn


def _birlestir_duz(video_yolu, ses_yolu, cikis_yolu, sure_sn=None, ilerleme=None):
    import os

    def moov_oku(yol):
        boyut_toplam = os.path.getsize(yol)
        with open(yol, "rb") as f:
            for pos, boyut, tip, baslik in _ust_kutular(f, boyut_toplam):
                if tip == b"moov":
                    f.seek(pos + baslik)
                    return f.read(boyut - baslik)
        raise MuxHatasi("moov bulunamadi")

    v_moov = moov_oku(video_yolu)
    a_moov = moov_oku(ses_yolu)
    v_coc, v_trak = _trak_bul(v_moov)
    a_coc, a_trak = _trak_bul(a_moov)

    v_id = a_eski = None
    for t, i in _cocuklar(v_trak):
        if t == b"tkhd":
            v_id, _ = _tkhd_id(i)
    for t, i in _cocuklar(a_trak):
        if t == b"tkhd":
            a_eski, _ = _tkhd_id(i)
    a_id = v_id + 1

    v_film = _film_olcegi(v_coc)
    a_film = _film_olcegi(a_coc)
    oran = v_film / a_film if a_film else 1.0

    v_olcek = _mdhd_zaman_olcegi(v_trak)
    a_olcek = _mdhd_zaman_olcegi(a_trak)
    v_parca = _iz_parcalari(video_yolu, v_id, v_olcek, _trex_varsayilan(v_moov, v_id))
    a_parca = _iz_parcalari(ses_yolu, a_eski, a_olcek, _trex_varsayilan(a_moov, a_eski))

    # cikti sirasi: zamana gore
    sira = [(p["t"], 0, i, p, video_yolu) for i, p in enumerate(v_parca)]
    sira += [(p["t"], 1, i, p, ses_yolu) for i, p in enumerate(a_parca)]
    sira.sort(key=lambda x: (x[0], x[1], x[2]))

    konum = 0
    for _, _, _, p, _ in sira:
        p["rel"] = konum
        konum += p["toplam"]
    veri_boyutu = konum
    buyuk = veri_boyutu > 0xFFFFFFFF - 64 * 1024 * 1024
    mdat_baslik = 16 if veri_boyutu + 8 > 0xFFFFFFFF else 8

    v_of = [p["rel"] for p in v_parca]
    a_of = [p["rel"] for p in a_parca]

    ftyp = _kutu(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41")

    def moov_kur(taban):
        v_yeni, v_sn = _trak_kur(v_trak, v_id, v_parca, v_of, taban, buyuk, v_film, 1.0,
                                 v_parca[0].get("tik") or 0)
        a_yeni, a_sn = _trak_kur(a_trak, a_id, a_parca, a_of, taban, buyuk, v_film, oran,
                                 a_parca[0].get("tik") or 0)
        toplam_sn = max(v_sn, a_sn)
        cocuklar = []
        for t, i in v_coc:
            if t == b"mvhd":
                yama, _ = _mvhd_yama(i, a_id + 1, toplam_sn)
                cocuklar.append((t, yama))
        cocuklar.append((b"trak", v_yeni))
        cocuklar.append((b"trak", a_yeni))
        return _kutu(b"moov", _birlestir(cocuklar))

    on_moov = moov_kur(0)
    taban = len(ftyp) + len(on_moov) + mdat_baslik
    moov = moov_kur(taban)
    if len(moov) != len(on_moov):
        raise MuxHatasi("moov boyutu tutarsiz")

    with open(cikis_yolu, "wb") as out:
        out.write(ftyp)
        out.write(moov)
        if mdat_baslik == 16:
            out.write(struct.pack(">I4sQ", 1, b"mdat", veri_boyutu + 16))
        else:
            out.write(struct.pack(">I4s", veri_boyutu + 8, b"mdat"))
        kaynaklar = {}
        yazilan = 0
        try:
            for no, (_, _, _, p, yol) in enumerate(sira, 1):
                f = kaynaklar.get(yol)
                if f is None:
                    f = kaynaklar[yol] = open(yol, "rb")
                for bas, ornekler in p["kosular"]:
                    kalan = sum(x[1] for x in ornekler)
                    f.seek(bas)
                    while kalan > 0:
                        blok = f.read(min(KOPYA_BOYUT, kalan))
                        if not blok:
                            raise MuxHatasi("kaynak dosya beklenenden kisa")
                        out.write(blok)
                        kalan -= len(blok)
                yazilan += p["toplam"]
                if ilerleme and no % 20 == 0:
                    ilerleme(yazilan / (veri_boyutu or 1))
        finally:
            for f in kaynaklar.values():
                f.close()
    if ilerleme:
        ilerleme(1.0)


def birlestir(video_yolu, ses_yolu, cikis_yolu, sure_sn=None, ilerleme=None):
    """Once klasik MP4 (ileri sarilabilir) dener; olmazsa parcali birlestirmeye doner."""
    import os
    try:
        _birlestir_duz(video_yolu, ses_yolu, cikis_yolu, sure_sn, ilerleme)
        return "duz"
    except Exception:
        try:
            os.remove(cikis_yolu)
        except OSError:
            pass
    birlestir_parcali(video_yolu, ses_yolu, cikis_yolu, sure_sn, ilerleme)
    return "parcali"
