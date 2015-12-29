import re
from six import string_types # for 2-3 compatibility
import types
from numbers import Number

#import pdb # debug only

core_types = [ ]

class SchemaError(Exception):
  pass

### Utility Functions --------------------------------------------------------

class Util(object):
  @staticmethod
  def indent(text, level=1, whitespace='  '):
    return '\n'.join(whitespace*level+line for line in text.split('\n'))

  @staticmethod
  def make_range_check(opt):

    if not {'min', 'max', 'min-ex', 'max-ex'}.issuperset(opt):
      raise ValueError("illegal argument to make_range_check")
    if {'min', 'min-ex'}.issubset(opt):
      raise ValueError("Cannot define both exclusive and inclusive min")
    if {'max', 'max-ex'}.issubset(opt):
      raise ValueError("Cannot define both exclusive and inclusive max")      

    r = opt.copy()
    inf = float('inf')

    def check_range(value):
      return(
        r.get('min',    -inf) <= value and \
        r.get('max',     inf) >= value and \
        r.get('min-ex', -inf) <  value and \
        r.get('max-ex',  inf) >  value
        )

    return check_range

### Schema Factory Class -----------------------------------------------------

class Factory(object):
  def __init__(self, register_core_types=True):
    self.prefix_registry = {
      '':      'tag:codesimply.com,2008:rx/core/',
      '.meta': 'tag:codesimply.com,2008:rx/meta/',
    }

    self.type_registry = {}
    if register_core_types:
      for t in core_types: self.register_type(t)

  @staticmethod
  def _default_prefixes(): pass

  def expand_uri(self, type_name):
    if re.match('^\w+:', type_name): return type_name

    m = re.match('^/([-._a-z0-9]*)/([-._a-z0-9]+)$', type_name)

    if not m:
      raise ValueError("couldn't understand type name '{}'".format(type_name))

    prefix, suffix = m.groups()

    if prefix not in self.prefix_registry:
      raise KeyError(
        "unknown prefix '{0}' in type name '{}'".format(prefix, type_name)
      )

    return self.prefix_registry[ prefix ] + suffix

  def add_prefix(self, name, base):
    if self.prefix_registry.get(name):
      raise SchemaError("the prefix '{}' is already registered".format(name))

    self.prefix_registry[name] = base;

  def register_type(self, t):
    t_uri = t.uri()

    if t_uri in self.type_registry:
      raise ValueError("type already registered for {}".format(t_uri))

    self.type_registry[t_uri] = t

  def learn_type(self, uri, schema):
    if self.type_registry.get(uri):
      raise SchemaError(
        "tried to learn type for already-registered uri {}".format(uri)
        )

    # make sure schema is valid
    # should this be in a try/except?
    self.make_schema(schema)

    self.type_registry[uri] = { 'schema': schema }

  def make_schema(self, schema):
    if isinstance(schema, string_types):
      schema = { 'type': schema }

    if not isinstance(schema, dict):
      raise SchemaError('invalid schema argument to make_schema')

    uri = self.expand_uri(schema['type'])

    if not self.type_registry.get(uri):
      raise SchemaError("unknown type {}".format(uri))

    type_class = self.type_registry[uri]

    if isinstance(type_class, dict):
      if not {'type'}.issuperset(schema):
        raise SchemaError('composed type does not take check arguments')
      return self.make_schema(type_class['schema'])
    else:
      return type_class(schema, self)

### Core Type Base Class -------------------------------------------------

class _CoreType(object):
  @classmethod
  def uri(self):
    return 'tag:codesimply.com,2008:rx/core/' + self.subname()

  def __init__(self, schema, rx):
    if not {'type'}.issuperset(schema):
      raise SchemaError('unknown parameter for //{}'.format(self.subname()))

  def check(self, value):
    return False

### Core Schema Types --------------------------------------------------------

class AllType(_CoreType):
  @staticmethod
  def subname(): return 'all'

  def __init__(self, schema, rx):
    if not {'type', 'of'}.issuperset(schema):
      raise SchemaError('unknown parameter for //all')
    
    if not schema.get('of'):
      raise SchemaError('no alternatives given in //all of')

    self.alts = [rx.make_schema(s) for s in schema['of']]

  def check(self, value):
    return all(schema.check(value) for schema in self.alts)


class AnyType(_CoreType):
  @staticmethod
  def subname(): return 'any'

  def __init__(self, schema, rx):
    self.alts = None

    if not {'type', 'of'}.issuperset(schema):
      raise SchemaError('unknown parameter for //any')
    
    if 'of' in schema:
      if not schema['of']: 
        raise SchemaError('no alternatives given in //any of')

      self.alts = [ rx.make_schema(alt) for alt in schema['of'] ]

  def check(self, value):
    return (
      self.alts is None or \
      any(schema.check(value) for schema in self.alts)
      )


class ArrType(_CoreType):
  @staticmethod
  def subname(): return 'arr'

  def __init__(self, schema, rx):
    self.length = None

    if not {'type', 'contents', 'length'}.issuperset(schema):
      raise SchemaError('unknown parameter for //arr')

    if not schema.get('contents'):
      raise SchemaError('no contents provided for //arr')

    self.content_schema = rx.make_schema(schema['contents'])

    if schema.get('length'):
      self.length = Util.make_range_check(schema['length'])

  def check(self, value):
    return(
      isinstance(value, (list, tuple))             and \
      (not self.length or self.length(len(value))) and \
      all(self.content_schema.check(item) for item in value)
      )


class BoolType(_CoreType):
  @staticmethod
  def subname(): return 'bool'

  def check(self, value):
    return isinstance(value, bool)


class DefType(_CoreType):
  @staticmethod
  def subname(): return 'def'

  def check(self, value):
    return value is not None


class FailType(_CoreType):
  @staticmethod
  def subname(): return 'fail'

  def check(self, value):
    return False


class IntType(_CoreType):
  @staticmethod
  def subname(): return 'int'

  def __init__(self, schema, rx):
    if not {'type', 'range', 'value'}.issuperset(schema):
      raise SchemaError('unknown parameter for //int')

    self.value = None
    if 'value' in schema:
      if not isinstance(schema['value'], Number) or schema['value'] % 1 != 0:
        raise SchemaError('invalid value parameter for //int')
      self.value = schema['value']

    self.range = None
    if 'range' in schema:
      self.range = Util.make_range_check(schema['range'])

  def check(self, value):
    return (
      isinstance(value, Number)                 and \
      not isinstance(value, bool)               and \
      value%1 == 0                              and \
      (self.range is None or self.range(value)) and \
      (self.value is None or value == self.value)
      )


class MapType(_CoreType):
  @staticmethod
  def subname(): return 'map'

  def __init__(self, schema, rx):
    self.allowed = set()

    if not {'type', 'values'}.issuperset(schema):
      raise SchemaError('unknown parameter for //map')

    if not schema.get('values'):
      raise SchemaError('no values given for //map')

    self.value_schema = rx.make_schema(schema['values'])

  def check(self, value):
    return(
      isinstance(value, dict) and \
      all(self.value_schema.check(v) for v in value.values())
      )


class NilType(_CoreType):
  @staticmethod
  def subname(): return 'nil'

  def check(self, value): return value is None


class NumType(_CoreType):
  @staticmethod
  def subname(): return 'num'

  def __init__(self, schema, rx):
    if not {'type', 'range', 'value'}.issuperset(schema):
      raise SchemaError('unknown parameter for //num')

    self.value = None
    if 'value' in schema:
      if not isinstance(schema['value'], Number):
        raise SchemaError('invalid value parameter for //num')
      self.value = schema['value']

    self.range = None

    if schema.get('range'):
      self.range = Util.make_range_check(schema['range'])

  def check(self, value):
    return (
      isinstance(value, Number)                 and \
      not isinstance(value, bool)               and \
      (self.range is None or self.range(value)) and \
      (self.value is None or value == self.value)
      )


class OneType(_CoreType):
  @staticmethod
  def subname(): return 'one'

  def check(self, value):
    return isinstance(value, (Number, string_types))


class RecType(_CoreType):
  @staticmethod
  def subname(): return 'rec'

  def __init__(self, schema, rx):
    if not {'type', 'rest', 'required', 'optional'}.issuperset(schema):
      raise SchemaError('unknown parameter for //rec')

    self.known = set()
    self.rest_schema = None
    if schema.get('rest'): self.rest_schema = rx.make_schema(schema['rest'])

    for which in ('required', 'optional'):
      setattr(self, which, {})
      for field in schema.get(which, {}).keys():
        if field in self.known:
          raise SchemaError(
            '%s appears in both required and optional' % field
            )

        self.known.add(field)

        self.__getattribute__(which)[field] = rx.make_schema(
          schema[which][field]
        )

  def check(self, value):
    if not isinstance(value, dict): return False

    unknown = [k for k in value.keys() if k not in self.known]

    if unknown and not self.rest_schema: return False

    for field in self.required:
      if field not in value or not self.required[field].check(value[field]):
        return False

    for field in self.optional:
      if field not in value: continue
      if not self.optional[field].check(value[field]): 
        return False

    if unknown:
      rest = {key: value[key] for key in unknown}
      if not self.rest_schema.check(rest): return False

    return True


class SeqType(_CoreType):
  @staticmethod
  def subname(): return 'seq'

  def __init__(self, schema, rx):
    if not {'type', 'contents', 'tail'}.issuperset(schema):
      raise SchemaError('unknown parameter for //seq')

    if not schema.get('contents'):
      raise SchemaError('no contents provided for //seq')

    self.content_schema = [ rx.make_schema(s) for s in schema['contents'] ]

    self.tail_schema = None
    if (schema.get('tail')):
      self.tail_schema = rx.make_schema(schema['tail'])

  def check(self, value):
    if not isinstance(value, (list, tuple)): return False

    if len(value) < len(self.content_schema):
      return False

    for i in range(len(self.content_schema)):
      if not self.content_schema[i].check(value[i]):
        return False

    if len(value) > len(self.content_schema):
      if not self.tail_schema: return False

      if not self.tail_schema.check(value[ len(self.content_schema) :  ]):
        return False

    return True;


class StrType(_CoreType):
  @staticmethod
  def subname(): return 'str'

  def __init__(self, schema, rx):
    if not {'type', 'value', 'length'}.issuperset(schema):
      raise SchemaError('unknown parameter for //str')

    self.value = None
    if 'value' in schema:
      if not isinstance(schema['value'], string_types):
        raise SchemaError('invalid value parameter for //str')
      self.value = schema['value']

    self.length = None
    if 'length' in schema:
      self.length = Util.make_range_check(schema['length'])

  def check(self, value):
    return (
      isinstance(value, string_types) and \
      (self.value  is None or value == self.value) and \
      (self.length is None or self.length(len(value)))
      )


core_types = [
  AllType,  AnyType, ArrType, BoolType, DefType,
  FailType, IntType, MapType, NilType,  NumType,
  OneType,  RecType, SeqType, StrType
]
