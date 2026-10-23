# Test fixtures

- kscreen_doctor_o.txt: real `kscreen-doctor -o` output from Matthew's PC, 23 Oct 2026 (colour codes removed).
- kscreen_doctor_j.json: `kscreen-doctor -j` in the libkscreen ConfigSerializer shape, rebuilt from the -o
  output above and the start of the real -j paste (the paste was cut off).
- Everything else is synthetic with the documented structure (no personal data): EE.cfg, cs2_video.txt,
  localconfig.vdf, loginusers.vdf, libraryfolders.vdf, appmanifests, GameUserSettings.ini (UE4, CRLF),
  autoexec.cfg (Source), brotato_save_v2.json, user.reg (Wine registry), MangoHud CSVs (make_logs.py).
- Added 23 Oct 2026 (more-adapters), synthetic with the documented structure, CRLF where the game is a Windows
  build: witcher3_dx12user.settings (sections and keys from a real pre 4.0 user.settings on GitHub,
  tafulop/Witcher-3-Wild-Hunt; values made up), drg_GameUserSettings.ini (Unreal 4 layout; the
  /Script/FSD.FSDGameUserSettings section name is a guess), xcom2_XComEngine.ini and
  dishonored_DishonoredEngine.ini (Unreal 3 layout; section names [U]), discoelysium_Settings.json (shape [U]).
