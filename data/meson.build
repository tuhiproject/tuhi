gnome = import('gnome')

metainfodir = join_paths(datadir, 'metainfo')

conf = configuration_data()
conf.set('version', meson.project_version())
conf.set('url', 'https://github.com/tuhiproject/tuhi')
conf.set('version_date', version_date)

about_dialog = configure_file(input: 'ui/AboutDialog.ui.in',
			      output: 'AboutDialog.ui',
			      configuration: conf)

install_data('org.freedesktop.Tuhi.svg', install_dir: icondir_scalable)
install_data('org.freedesktop.Tuhi-symbolic.svg', install_dir: icondir_symbolic)

i18n.merge_file(input: 'org.freedesktop.Tuhi.desktop.in',
                output: 'org.freedesktop.Tuhi.desktop',
                type: 'desktop',
                po_dir: podir,
                install: true,
                install_dir: desktopdir)

appdata = configure_file(input: 'org.freedesktop.Tuhi.appdata.xml.in.in',
                         output: 'org.freedesktop.Tuhi.appdata.xml.in',
                         configuration: conf)

i18n.merge_file(input: appdata,
                output: 'org.freedesktop.Tuhi.appdata.xml',
                type: 'xml',
                po_dir: podir,
                install: true,
                install_dir: metainfodir)


gnome.compile_resources('tuhi', 'tuhi.gresource.xml',
			source_dir: '.',
			dependencies: [about_dialog],
			gresource_bundle: true,
			install: true,
			install_dir: pkgdatadir)
