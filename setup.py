#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup

setup(
    name='eigakan',
    version='0.7',
    packages=['eigakan'],
    url='',
    license='',
    author='bigretromike',
    author_email='',
    description='eigakan',
    install_requires=[
        'winpexpect',
        'progressbar2',
        'flask',
        'urllib3',
        'shutil',
        'subprocess'
    ]
)
