{pkgs, ...}: {
  xdg.configFile."vimiv/vimiv.conf".text = ''
    [GENERAL]
    monitor_filesystem = True
    startup_library = True
    style = dracula
    read_only = False

    [COMMAND]
    history_limit = 100

    [COMPLETION]
    fuzzy = False

    [SEARCH]
    ignore_case = True
    incremental = True

    [IMAGE]
    autoplay = True
    autowrite = ask
    overzoom = 1.0
    zoom_wheel_ctrl = True

    [LIBRARY]
    width = 0.3
    show_hidden = False

    [THUMBNAIL]
    size = 128
    save = True

    [SLIDESHOW]
    delay = 2.0
    indicator = slideshow:

    [STATUSBAR]
    collapse_home = True
    show = True
    message_timeout = 60000
    mark_indicator = <b>*</b>
    left = {pwd}{read-only}
    left_image = {index}/{total} {basename}{read-only} [{zoomlevel}]
    left_thumbnail = {thumbnail-index}/{thumbnail-total} {thumbnail-basename}{read-only}
    left_manipulate = {basename}   {image-size}   Modified: {modified}   {processing}
    center_thumbnail = {thumbnail-size}
    center = {slideshow-indicator} {slideshow-delay} {transformation-info}
    right = {keys}  {mark-count}  {mode}
    right_image = {keys}  {mark-indicator} {mark-count}  {mode}

    [KEYHINT]
    delay = 500
    timeout = 5000

    [TITLE]
    fallback = vimiv
    image = vimiv - {basename}

    [SORT]
    image_order = alphabetical
    directory_order = alphabetical
    reverse = False
    ignore_case = False
    shuffle = False

    [PLUGINS]
    print = default
    metadata = default
  '';

  xdg.configFile."vimiv/styles/dracula".text = ''
    [STYLE]
    base00 = #282a36
    base01 = #44475a
    base02 = #44475a
    base03 = #6272a4
    base04 = #f8f8f2
    base05 = #f8f8f2
    base06 = #f8f8f2
    base07 = #f8f8f2
    base08 = #ff5555
    base09 = #ffb86c
    base0a = #f1fa8c
    base0b = #50fa7b
    base0c = #8be9fd
    base0d = #6272a4
    base0e = #bd93f9
    base0f = #ff79c6
    font = 10pt Monospace
    image.bg = #282a36
    image.scrollbar.width = 8px
    image.scrollbar.bg = #282a36
    image.scrollbar.fg = #6272a4
    image.scrollbar.padding = 2px
    library.font = 10pt Monospace
    library.fg = #f8f8f2
    library.padding = 2px
    library.directory.fg = #8be9fd
    library.even.bg = #282a36
    library.odd.bg = #282a36
    library.selected.bg = #bd93f9
    library.selected.fg = #282a36
    library.search.highlighted.fg = #282a36
    library.search.highlighted.bg = #f1fa8c
    library.scrollbar.width = 8px
    library.scrollbar.bg = #282a36
    library.scrollbar.fg = #6272a4
    library.scrollbar.padding = 2px
    library.border = 0px solid
    statusbar.font = 10pt Monospace
    statusbar.bg = #44475a
    statusbar.fg = #f8f8f2
    statusbar.error = #ff5555
    statusbar.warning = #ffb86c
    statusbar.info = #8be9fd
    statusbar.message_border = 2px solid
    statusbar.padding = 4
    thumbnail.font = 10pt Monospace
    thumbnail.fg = #f8f8f2
    thumbnail.bg = #282a36
    thumbnail.padding = 20
    thumbnail.selected.bg = #bd93f9
    thumbnail.search.highlighted.bg = #f1fa8c
    thumbnail.default.bg = #44475a
    thumbnail.error.bg = #ff5555
    thumbnail.frame.fg = #6272a4
    completion.height = 16em
    completion.fg = #f8f8f2
    completion.even.bg = #282a36
    completion.odd.bg = #44475a
    completion.selected.fg = #282a36
    completion.selected.bg = #bd93f9
    keyhint.padding = 2px
    keyhint.border_radius = 10px
    keyhint.suffix_color = #8be9fd
    manipulate.fg = #f8f8f2
    manipulate.focused.fg = #8be9fd
    manipulate.bg = #282a36
    manipulate.slider.left = #bd93f9
    manipulate.slider.handle = #6272a4
    manipulate.slider.right = #44475a
    manipulate.image.border = 2px solid
    manipulate.image.border.color = #8be9fd
    mark.color = #ff79c6
    keybindings.bindings.color = #8be9fd
    keybindings.highlight.color = #bd93f9
    metadata.padding = 2px
    metadata.border_radius = 10px
    image.straighten.color = #f1fa8c
    prompt.font = 10pt Monospace
    prompt.fg = #f8f8f2
    prompt.bg = #44475a
    prompt.padding = 2px
    prompt.border_radius = 10px
    prompt.border = 2px solid
    prompt.border.color = #bd93f9
    crop.shading = #88000000
    crop.border = 2px solid
    crop.border.color = #88bd93f9
    crop.grip.color = #88f8f8f2
    crop.grip.border = 2px solid
    crop.grip.border.color = #88f8f8f2
    library.selected.bg.unfocus = #88bd93f9
    thumbnail.selected.bg.unfocus = #88bd93f9
    metadata.bg = #AA44475a

    ; vim:ft=dosini
  '';
}
