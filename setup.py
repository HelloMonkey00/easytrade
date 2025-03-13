#!/usr/bin/env python
"""
Setup script for the EasyTrade package.
"""
from setuptools import setup, find_packages

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name="easytrade",
    version="0.1.0",
    author="EasyTrade Team",
    author_email="info@easytrade.com",
    description="A modular Python framework for quantitative trading",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/easytrade/easytrade",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Financial and Insurance Industry",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.12",
        "Topic :: Office/Business :: Financial :: Investment",
        "Topic :: Scientific/Engineering :: Information Analysis",
    ],
    python_requires=">=3.12",
    install_requires=[
        "numpy>=1.26.0",
        "pandas>=2.2.0",
        "matplotlib>=3.8.0",
        "pydantic>=2.6.0",
        "python-dateutil>=2.8.2",
        "pytz>=2024.1",
        "pyyaml>=6.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=8.0.0",
            "pytest-cov>=4.1.0",
            "black>=24.1.0",
            "isort>=5.13.0",
            "flake8>=7.0.0",
            "mypy>=1.8.0",
        ],
        "backtrader": [
            "backtrader>=1.9.78.123",
        ],
    },
) 