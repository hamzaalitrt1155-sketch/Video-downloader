[app]
title = Video Indirici
package.name = videoindirici
package.domain = org.benim
source.dir = .
source.include_exts = py
version = 0.1
requirements = python3,kivy==2.3.0,yt-dlp,certifi,openssl
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.api = 29
android.minapi = 21
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
