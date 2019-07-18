project('tuhi',
	version: '0.1',
	license: 'GPLv2',
	meson_version: '>= 0.48.0')
# The tag date of the project_version(), update when the version bumps.
version_date='2019-07-10'
# Note: Update the Contributor list in data/ui/AboutDialog.ui.in when the
# version bumps

# Dependencies
dependency('python3', required: true)
dependency('pygobject-3.0', required: true)

# Gtk version required
gtk_major_version = 3
gtk_minor_version = 22

prefix = get_option('prefix')
datadir = join_paths(prefix, get_option('datadir'))
localedir = join_paths(prefix, get_option('localedir'))
pkgdatadir = join_paths(datadir, meson.project_name())
bindir = join_paths(prefix, get_option('bindir'))
podir = join_paths(meson.source_root(), 'po')
desktopdir = join_paths(datadir, 'applications')
icondir = join_paths(datadir, 'icons', 'hicolor', 'scalable', 'apps')
metainfodir = join_paths(datadir, 'metainfo')

i18n = import('i18n')

subdir('po')
subdir('tuhigui/data')

# Find the directory to install our Python code
pymod = import('python')
py3 = pymod.find_installation()
python_dir = py3.get_install_dir()
install_subdir('tuhigui/tuhigui', install_dir: python_dir, exclude_directories: '__pycache__')

config_tuhigui = configuration_data()
config_tuhigui.set('pkgdatadir', pkgdatadir)
config_tuhigui.set('localedir', localedir)
config_tuhigui.set('gtk_major_version', gtk_major_version)
config_tuhigui.set('gtk_minor_version', gtk_minor_version)
config_tuhigui.set('devel', '')

config_tuhigui_devel = config_tuhigui
config_tuhigui_devel.set('pkgdatadir', join_paths(meson.build_root(), 'tuhigui', 'data'))
config_tuhigui_devel.set('localedir', join_paths(meson.build_root(), 'po'))
config_tuhigui_devel.set('devel', '''
sys.path.insert(1, '@0@')
print('Running from source tree, using local files')
'''.format(meson.source_root()))

configure_file(input: 'tuhi-gui.in',
	       output: 'tuhi-gui',
	       configuration: config_tuhigui,
	       install_dir: bindir)

configure_file(input: 'tuhi-gui.in',
	       output: 'tuhi-gui.devel',
	       configuration: config_tuhigui_devel)

meson.add_install_script('meson_install.sh')

desktop_file = i18n.merge_file(input: 'tuhigui/data/org.freedesktop.Tuhi.desktop.in',
                               output: 'org.freedesktop.Tuhi.desktop',
                               type: 'desktop',
                               po_dir: podir,
                               install: true,
                               install_dir: desktopdir)

conf = configuration_data()
conf.set('version', meson.project_version())
conf.set('url', 'https://github.com/tuhiproject/tuhi')
conf.set('version_date', version_date)

appdata_intl = configure_file(input: 'tuhigui/data/org.freedesktop.Tuhi.appdata.xml.in.in',
                              output: 'org.freedesktop.Tuhi.appdata.xml.in',
                              configuration: conf)

appdata = i18n.merge_file(input: appdata_intl,
                          output: 'org.freedesktop.Tuhi.appdata.xml',
                          type: 'xml',
                          po_dir: podir,
                          install: true,
                          install_dir: metainfodir)

install_data('tuhigui/data/org.freedesktop.Tuhi.svg', install_dir: icondir)

flake8 = find_program('flake8-3', required: false)
if flake8.found()
   test('flake8', flake8,
        args: ['--ignore=E501,W504',
               join_paths(meson.source_root(), 'tuhigui/')])
endif

desktop_validate = find_program('desktop-file-validate', required: false)
if desktop_validate.found()
    test('desktop-file-validate', desktop_validate, args: [desktop_file])
endif

appstream_util = find_program('appstream-util', required: false)
if appstream_util.found()
    test('appstream-util validate-relax', appstream_util,
         args: ['validate-relax', appdata])
endif

# A wrapper to start tuhi at the same time as tuhigui, used by the flatpak
configure_file(input: 'tools/tuhi-gui-flatpak.py',
               output: 'tuhi-gui-flatpak.py',
               copy: true)
