#!/usr/bin/env python
"""
Script to run tests for the EasyTrade framework.
"""
import os
import sys
import unittest
import argparse


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Run tests for the EasyTrade framework')
    
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose output')
    parser.add_argument('--test-dir', type=str, default='tests',
                       help='Directory containing tests')
    parser.add_argument('--pattern', type=str, default='test_*.py',
                       help='Pattern to match test files')
    
    return parser.parse_args()


def main():
    """Run the tests."""
    args = parse_args()
    
    # Discover and run tests
    loader = unittest.TestLoader()
    tests = loader.discover(args.test_dir, pattern=args.pattern)
    
    runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1)
    result = runner.run(tests)
    
    # Return non-zero exit code if tests failed
    sys.exit(not result.wasSuccessful())


if __name__ == '__main__':
    main() 