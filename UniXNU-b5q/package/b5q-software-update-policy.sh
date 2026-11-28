#!/bin/sh
# Keep softwareupdated's XPC service available without background downloads.
set -eu
domain=/Library/Preferences/com.apple.SoftwareUpdate
test ! -L "$domain.plist"
for key in AutomaticCheckEnabled AutomaticDownload AutomaticallyInstallMacOSUpdates CriticalUpdateInstall; do
    /usr/bin/defaults write "$domain" "$key" -bool false
done
