#!/usr/bin/env python

from setuptools import setup

setup(
    name="mtracker",
    version="1.0.0",
    author="CERT Polska",
    author_email="info@cert.pl",
    description="A framework and web interface for botnet tracking",
    packages=[
        "mtracker",
    ],
    package_dir={"mtracker": "src"},
    include_package_data=True,
    url="https://github.com/CERT-Polska/mtracker",
    install_requires=open("requirements.txt").read().splitlines(),
    python_requires=">=3.7",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Programming Language :: Python",
        "Operating System :: OS Independent",
        "OSI Approved :: BSD License",
        "Topic :: Security",
    ],
)
