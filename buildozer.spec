
[app]
title = Video Indirici
package.name = videoindirici
package.domain = org.benim
source.dir = .
source.include_exts = py
version = 0.1
requirements = python3==3.11.5,hostpython3==3.11.5,kivy==2.3.0,yt-dlp,certifi,openssl
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.api = 29
android.minapi = 21
android.ndk = 25b
android.archs = arm64-v8a
icon.filename = %(source.dir)s/icon.png
icon.adaptive_foreground.filename = %(source.dir)s/icon_fg.png
icon.adaptive_background.filename = %(source.dir)s/icon_bg.png
android.accept_sdk_license = True
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
