# Abroad for Android

This folder builds **Abroad.apk**, the phone client for the marketplace.

## What the APK is

Abroad is a Flask application with a SQLite database, so the site keeps running on
the computer. The APK is a small native Android app that opens those same pages in
a full-screen WebView, with the Abroad logo as the launcher icon. Nothing is
re-implemented: the phone talks to the running Flask server, so anything a browser
can do on the site works in the app, including signing in, uploads and escrow codes.

Because the public address of the Cloudflare quick tunnel changes on every start,
the app asks for the link once on the first screen and remembers it:

1. On the computer run `start-abroad.cmd`.
2. Run `tunnel-abroad.cmd` and copy the `https://....trycloudflare.com` link.
3. In the app, paste the link and tap **Open marketplace**.

If the site later shows "Can't reach Abroad", the computer is off or the tunnel was
restarted: start the tunnel again and use **Change the link** with the new address.
An `http://192.168.x.x:5000` address also works while the phone is on the same
Wi-Fi network, as long as the Flask server listens on that interface.

The app also provides:

- Android back button = browser back inside the site.
- The system file picker, so receipt, product and flight-document uploads work.
- Clear-text HTTP allowed, so a plain local address can be used during a demo.

## Install on a phone

Copy `abroad-mobile-1.0.0.apk` to the phone (USB, Google Drive, or the GitHub
release asset) and open it. Android asks once to allow installing from that source
("Install unknown apps" for the file manager or browser). The APK is self-signed,
so Play Protect may show a warning — choose *Install anyway*.

`minSdkVersion` is 21 (Android 5.0) and `targetSdkVersion` is 34.

## Rebuilding

The build needs a JDK 17+ and an Android SDK with `platforms;android-34` and
`build-tools;34.0.0`. Gradle and Android Studio are not required:

```bash
JAVA_HOME=/path/to/jdk ANDROID_SDK=/path/to/android-sdk ./android/build.sh
```

The script compiles the resources with `aapt2`, the Java with `javac`, converts it
with `d8`, aligns with `zipalign` and signs with `apksigner`. It writes the APK to
`abroad-mobile-1.0.0.apk` in the project root (pass another path as the first
argument). On the first run it creates `android/abroad-release.jks` with the
password `abroad-classroom`; that key is not in Git, so keep it if you want a later
build to install over the old one — a different key means uninstalling first.

This is a classroom signing key, not a Play Store key: the app is meant to be
sideloaded, not published.

## Files

```
AndroidManifest.xml                              package, permissions, launcher activity
java/com/abroad/marketplace/MainActivity.java    WebView, link screen, uploads, back button
res/values/strings.xml                           app name
res/mipmap-*/ic_launcher.png                     launcher icons made from assets/logo.png
res/drawable-nodpi/logo.png                      logo shown on the link screen
build.sh                                         builds the signed APK
```
