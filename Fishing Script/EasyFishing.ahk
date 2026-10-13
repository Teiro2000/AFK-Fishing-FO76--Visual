#Requires AutoHotkey v2.0
#SingleInstance Force

; EASY FISHING

; Variables to edit:
; square1Pos is position of any pixel inside pink square (top-left corner) in fishing menu
; square2Pos is position of any pixel in black square diagonally down-right from pink square

; If squares are not showing, you have not installed EasyFishing.ba2 correctly

; For 1920x1080 use square1Pos(2,2) square2Pos(7,7)
; For 2560x1440 use square1Pos(2,2) square2Pos(10,10)
; For other resolutions:
;    1. Take a screenshot while in fishing menu
;    2. Paste it in any image editing program (like paint)
;    3. Put your cursor anywhere in pink square, mouse position will be shown somewhere in program
;       in paint position is shown in the bottom-left corner
;    4. Copy mouse position values to square1PosX (first value) and square1PosY (second value) below
;    5. Repeat steps 3. and 4. for square2 - black square diagonally down-right from pink one

square1PosX := 2
square1PosY := 2
square2PosX := 7
square2PosY := 7

showDebugTooltip := true
tooltipPosX := 1650
tooltipPosY := 520

; autoFish.py passes the positions for the current resolution on the command line:
;   AutoHotkey64.exe EasyFishing.ahk square1X square1Y square2X square2Y [tooltipX tooltipY]
; Without arguments the 1920x1080 values above are used.
if (A_Args.Length >= 4)
{
	square1PosX := Integer(A_Args[1])
	square1PosY := Integer(A_Args[2])
	square2PosX := Integer(A_Args[3])
	square2PosY := Integer(A_Args[4])
}
if (A_Args.Length >= 6)
{
	tooltipPosX := Integer(A_Args[5])
	tooltipPosY := Integer(A_Args[6])
}

; Read pixels from the whole screen, the same way autoFish.py does
CoordMode "Pixel", "Screen"
CoordMode "ToolTip", "Screen"



; Below this point you can change keybinds for starting and stopping fishing script
; Default values are f5 for starting script, f6 for reloading changes from file, and f8 for exiting
; List of all keys: https://www.autohotkey.com/docs/v2/KeyList.htm

F5::
{
	Loop
	{
		color1 := PixelGetColor(square1PosX, square1PosY)
		if (color1 != 0xF7A0B5)
		{
			if (showDebugTooltip)
				ToolTip "Not fishing", tooltipPosX, tooltipPosY
			continue
		}
		if (showDebugTooltip)
			ToolTip "Fishing", tooltipPosX, tooltipPosY
		color3 := PixelGetColor(square1PosX, square2PosY)
		state := getBlue(color3)
		if (state == 5)
		{
			isMinigame := true
			while (isMinigame)
			{
				color2 := PixelGetColor(square2PosX, square1PosY)
				xPos := getRed(color2) - 150
				yPos := getGreen(color2) - 150
				if (xPos != -150 || yPos != -150)
				{
					; Relative mouse move; "Int" so negative values go through as-is
					DllCall("mouse_event", "UInt", 0x1, "Int", xPos * 5, "Int", yPos * 5, "UInt", 0, "UPtr", 0)
				}
				else
				{
					isMinigame := false
				}
				if (showDebugTooltip)
					ToolTip "Minigame (x:" xPos " y:" yPos ")", tooltipPosX, tooltipPosY
			}
		}
		Sleep 20
	}
}

F6::Reload

F8::ExitApp


; PixelGetColor returns "0xRRGGBB"
getRed(color) {
	return (Integer(color) >> 16) & 0xFF
}
getGreen(color) {
	return (Integer(color) >> 8) & 0xFF
}
getBlue(color) {
	return Integer(color) & 0xFF
}
