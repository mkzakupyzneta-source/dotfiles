local wezterm = require 'wezterm'
local config = wezterm.config_builder()


config.colors = {
  foreground = '#CCCCCC',
  background = '#0C0C0C',
  cursor_bg = '#CCCCCC',
  cursor_fg = '#0C0C0C',
  ansi = {'#0C0C0C','#C50F1F','#13A10E','#C19C00','#0037DA','#881798','#3A96DD','#CCCCCC'},
  brights = {'#767676','#E74856','#16C60C','#F9F1A5','#3B78FF','#B4009E','#61D6D6','#F2F2F2'},
}

return config
