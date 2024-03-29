![Python Package Test and Build](https://github.com/The7BridgesTeam/Converters/actions/workflows/python-package.yml/badge.svg?branch=master)

# Converters

## Install

Install using pip:

```
pip install python-converters
```

## Overview

At its most basic, **Converters** provides a small in-python DSL / declarative mechanism to define transformations operations (”conversions") that allow you to rename, alter, add, clean etc. fields of objects / maps conveniently, making it easy to work with nested structures and a host of other common cases.

Here is a quick example of using a subclass of `Converter` to convert from one
instance to another:

```py
from converters import Converter

class MyConverter(Converter):
    from_class = dict
    to_class = dict

    conversions = [
        'a',                            # to['a'] = from['a']
        ('b', 'a'),                     # to['b'] = from['a']
        ('c', NOS, 'a default'),        # to['c'] = 'a default'
        ('d', 'a', lambda x: x * 2),    # to['d'] = from['a'] * 2
        ('e', NOS, dict),               # to['e'] = dict()
    ]

MyConverter({'a': 1}).convert()
# yields {'a': 1, 'b': 1, 'c': 'a default', 'd': 2, 'e': {}}
```

But that is just the beginning. Its real power comes as you start to nest converters and subclass the core converter class to support different data formats. The power of it is that you can get going with very simple examples, but as your needs grow you’ll find that converters rises to meet them, and are highly extendable for the cases where they don’t.

And to get you started there are already extensions for converting to and from:

- django models
- XML documents
- pandas dataframes
- fixed width string formats (!)


## Why is this useful?

Doing conversions of data (e.g. ingest, exgest) normally seems like a simple job, but naive approaches end up writing a lot of (often 
one-off) boilerplate and repetitive code that is hard to read and update, inconsistent and error prone, with code often spread throughout 
several ad hoc functions. Converters provides a single place to put conversions, uses class inheritance to share domain-specific 
operations, and through that and its maximal approach to features minimizes client boilerplate.
