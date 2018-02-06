#!/usr/bin/python3

from setuptools import setup

setup(name='tuhi',
      version='0.1',
      description='A daemon to access Wacom Smartpad devices',
      long_description=open('README.md', 'r').read(),
      url='http://github.com/tuhiproject/tuhi',
      packages=['tuhi'],
      author='The Tuhi Developers',
      author_email='check-github-for-contributors@example.com',
      license='GPL',
      entry_points={
          "console_scripts": ['tuhi = tuhi.base:main']
      },
      classifiers=[
          'Development Status :: 3 - Alpha',
          'License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)',
          'Programming Language :: Python :: 3',
          'Programming Language :: Python :: 3.6'
      ],
      python_requires='>=3.6'
      )
