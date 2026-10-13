AFK Fishing FO76 - Visual version

Requirements
- Python 3 with: pip install mss numpy
- AutoHotkey v2 and v1 (C:\Program Files\AutoHotkey) - v1 runs EasyFishing.ahk,
  without it the 1080p-only easyFishing.exe is used
- Fishing.ba2 installed (draws the pink marker EasyFishing and this script rely on)
- Game in borderless fullscreen on the primary monitor (any 16:9 resolution)
- Nuka Quantum Bobber


1. Under Game settings disable C.A.M.P. Weather and Intense Weather Effects
2. Walk up to water and enter fishing mode
3. Double-click "Start Fishing.bat" and press Start
   (or run "Fishing Script/autoFish.py" for the console version)

How it works
- "E) CAST" prompt visible          -> press E to cast
- Cyan bobber floating in the water -> wait
- Bobber disappears (bite)          -> press E to reel, easyFishing.exe plays the minigame
- Back to "E) CAST"                 -> repeat

Tuning
The GUI shows live CAST prompt and bobber pixel counts next to their thresholds.
If the bobber isn't detected (its count stays near 0 while it's floating),
lower "Bobber min pixels" and press Apply & save. Settings are kept in
Fishing Script/settings.json.

Resolution
Detection areas and pixel thresholds scale with the screen size automatically
(the log shows the detected resolution on Start). EasyFishing's minigame
square positions are worked out too: (2,2)/(7,7) at 1080p, (2,2)/(10,10) at
1440p, (2,2)/(14,14) at 4K. If the minigame doesn't react, set
"Minigame square 1/2" in the settings by hand (see the comments at the top of
EasyFishing.ahk for how to find them) - changes apply on the next Start.
