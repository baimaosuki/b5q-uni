// SPDX-License-Identifier: BSD-2-Clause-Patent
// The pinned core's weak PE_builtin_boot_args is the normal board-policy
// interface. Keep the loader command line unchanged; explicit arguments win.
// Exact daemon paths come from 26C5035r's LaunchDaemons/LaunchAgents.
char PE_builtin_boot_args[] =
"exec-stand-in=/private/var/ngpu/bin/b5q-absentd deny-exec=/usr/libexec/mobileactivationd,/usr/libexec/cryptexd b5q-dpi=425 gpu-bundle-system=1";
