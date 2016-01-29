###########################################################################
# Data model
#
# This is a transitional AST structure; it defines an object model that
# is structured like C++, but outputs Python. At the top of the tree is
# a Module definition.
###########################################################################
from __future__ import unicode_literals, print_function

import sys

from collections import OrderedDict

from clang.cindex import TypeKind

# Python 2 compatibility shims
if sys.version_info.major <= 2:
    text = unicode
else:
    text = str


__all__ = (
    'CONSUMED', 'UNDEFINED',
    'Module',
    'Enumeration', 'EnumValue',
    'Function', 'Parameter', 'Variable',
    'Class', 'Struct', 'Union',
    'Attribute', 'Constructor', 'Destructor', 'Method',
    'Return', 'Block', 'If',
    'VariableReference', 'TypeReference', 'PrimitiveTypeReference', 'AttributeReference', 'SelfReference',
    'Literal', 'ListLiteral',
    'UnaryOperation', 'BinaryOperation', 'ConditionalOperation',
    'Parentheses', 'ArraySubscript',
    'Cast', 'Invoke', 'New',
)


# A marker for token use during macro expansion
CONSUMED = object()

# A marker for unknown values
UNDEFINED = object()


class Expression(object):
    # An expression is the left node of the AST. Operations,
    # literals, and references to attributes/members are all
    # expresisons. Expressions don't have context
    def __repr__(self):
        return "<%s>" % (self.__class__.__name__)

    def clean_argument(self):
        return self


class Declaration(Expression):
    # A Declaration is a named expression. As they are named,
    # They must belong to a context; that context provides the
    # scope in which the declaration is valid.
    # An anonymous declaration is a declaration without a
    # discoverable name.
    def __init__(self, context, name):
        self.context = context
        self.name = name

        if context and name:
            self.context.names[self.name] = self

    def __repr__(self):
        try:
            return "<%s %s>" % (self.__class__.__name__, self.full_name)
        except:
            return "<%s %s>" % (self.__class__.__name__, self.name)

    @property
    def full_name(self):
        if self.context:
            return '::'.join([self.context.full_name, self.name])
        return self.name

    @property
    def root(self):
        if self.context is None:
            return self
        else:
            return self.context.root


class Context(Declaration):
    # A context is a scope in for declaration names. Contexts
    # are heirarchical - the can be part of other contexts.
    def __init__(self, context, name):
        super(Context, self).__init__(context=context, name=name)
        self.names = OrderedDict()

    def __getitem__(self, name):
        # The name we're looking for might be annotated with
        # const, class, or any number of other descriptors.
        # Remove them, and then remove any extra spaces so that
        # we're left with a compact type name.
        name = name.replace('const', '')
        name = name.replace('class', '')
        name = name.replace('virtual', '')
        name = name.replace(' ', '')

        # If the name is scoped, do a lookup from the root node.
        # Otherwise, just look up the name in the current context.
        if '::' in name:
            parts = name.split('::')
            # print("LOOK FOR NAME", parts)
            decl = self.root
            for part in parts:
                decl = decl[part]
            return decl
        else:
            try:
                # print("LOOK FOR NAME PART", name, "in", self.name, '->', self.names)
                return self.names[name]
            except KeyError:
                if self.context:
                    return self.context.__getitem__(name)
                else:
                    raise

    def declare(self, name):
        self.names[name] = None


###########################################################################
# Modules
###########################################################################

class Module(Context):
    def __init__(self, name, context=None):
        super(Module, self).__init__(context=context, name=name)
        self.declarations = OrderedDict()
        self.imports = {}
        self.submodules = {}

    def add_to_context(self, context):
        context.add_submodule(self)

    def add_declaration(self, decl):
        self.declarations[decl.name] = decl
        decl.add_imports(self)

    def add_import(self, path, symbol=None):
        self.imports.setdefault(path, set()).add(symbol)

    def add_imports(self, module):
        pass

    def add_submodule(self, module):
        self.submodules[module.name] = module

    def output(self, out):
        if self.imports:
            for path in sorted(self.imports):
                if self.imports[path]:
                    out.write('from %s import %s' % (
                        path,
                        ', '.join(sorted(self.imports[path]))
                    ))
                else:
                    out.write('import %s' % path)
                out.clear_line()

        out.clear_major_block()
        for name, decl in self.declarations.items():
            out.clear_minor_block()
            decl.output(out)
        out.clear_line()


###########################################################################
# Enumerated types
###########################################################################

class Enumeration(Context):
    def __init__(self, context, name):
        super(Enumeration, self).__init__(context=context, name=name)
        self.enumerators = []

    def add_enumerator(self, enumerator):
        self.enumerators.append(enumerator)
        self.context.names[enumerator.name] = enumerator
        enumerator.enumeration = self

    def add_to_context(self, context):
        context.add_declaration(self)

    def add_imports(self, module):
        module.add_import('enum', 'Enum')

    def output(self, out):
        out.clear_major_block()
        out.write("class %s(Enum):" % self.name)
        out.start_block()
        if self.enumerators:
            for enumerator in self.enumerators:
                out.clear_line()
                out.write("%s = %s" % (
                    enumerator.name, enumerator.value
                ))
        else:
            out.clear_line()
            out.write('pass')
        out.end_block()


class EnumValue(Declaration):
    # A value in an enumeration.
    # EnumValues are slightly odd, becaues they are Declarations
    # in the same context as the Enumeration they belong to.
    def __init__(self, context, name, value):
        super(EnumValue, self).__init__(context, name)
        self.name = name
        self.value = value
        self.enumeration = None

    def add_imports(self, module):
        if module.full_name != self.context.context.full_name:
            module.add_import(
                self.context.context.full_name.replace('::', '.'),
                self.context.name
            )

    def output(self, out):
        out.write('%s.%s' % (self.enumeration.name, self.name))


###########################################################################
# Functions
###########################################################################

class Function(Context):
    def __init__(self, context, name):
        super(Function, self).__init__(context=context, name=name)
        self.parameters = []
        self.statements = None

    def add_parameter(self, parameter):
        self.parameters.append(parameter)

    def add_to_context(self, context):
        context.add_declaration(self)

    def add_import(self, scope, name):
        self.context.add_import(scope, name)

    def add_imports(self, module):
        pass

    def add_statement(self, statement):
        self.statements.append(statement)
        statement.add_imports(self.context)

    def output(self, out):
        out.clear_major_block()
        out.write('def %s(' % self.name)
        for i, param in enumerate(self.parameters):
            if i != 0:
                out.write(', ')
            param.output(out)
        out.write('):')
        out.start_block()
        if self.statements:
            for statement in self.statements:
                out.clear_line()
                statement.output(out)
        else:
            out.clear_line()
            out.write('pass')
        out.end_block()


class Parameter(Declaration):
    def __init__(self, function, name, ctype, default):
        super(Parameter, self).__init__(context=function, name=name)
        self.ctype = ctype
        self.default = default

    def add_to_context(self, context):
        context.add_parameter(self)

    def add_imports(self, module):
        pass

    def output(self, out):
        out.write(self.name)
        if self.default != UNDEFINED:
            out.write('=')
            self.default.output(out)


class Variable(Declaration):
    def __init__(self, context, name, value=None):
        super(Variable, self).__init__(context=context, name=name)
        self.value = value

    def add_to_context(self, context):
        context.add_declaration(self)

    def add_imports(self, module):
        if self.value:
            self.value.add_imports(module)

    def output(self, out):
        out.write('%s = ' % self.name)
        if self.value:
            self.value.output(out)
        else:
            out.write('None')
        out.clear_line()


###########################################################################
# Structs
###########################################################################

class Struct(Context):
    def __init__(self, context, name):
        super(Struct, self).__init__(context=context, name=name)
        # self.module is the module in which this class is defined.
        # self.context is the containing context. This is the same as
        #   self.module in the normal case, but will be the outer class
        #   in the case of a nested class definition.
        self.module = context
        while not isinstance(self.module, Module):
            self.module = self.module.context

        self.superclass = None
        self.constructors = {}
        self.destructor = None
        self.attributes = OrderedDict()
        self.methods = OrderedDict()
        self.classes = OrderedDict()

    def add_imports(self, module):
        pass

    def add_declaration(self, klass):
        self.classes[klass.name] = klass

    def add_constructor(self, method):
        print("Ignoring constructor for struct %s" % self.name, file=sys.stderr)

    def add_destructor(self, method):
        if self.destructor:
            if self.destructor.statements is None:
                self.destructor = method
            else:
                raise Exception("Cannot handle multiple desructors")
        else:
            self.destructor = method

    def add_attribute(self, attr):
        self.attributes[attr.name] = attr

    def add_method(self, method):
        self.methods[method.name] = method

    def add_to_context(self, context):
        context.add_declaration(self)

    def output(self, out):
        out.clear_major_block()
        if self.superclass:
            out.write("class %s(%s):" % (self.name, self.superclass))
        else:
            out.write("class %s:" % self.name)
        out.start_block()

        if self.attributes or self.destructor or self.classes or self.methods:
            if self.attributes:
                params = ''.join(', %s=None' % name for name in self.attributes.keys())
                out.clear_line()
                out.write('def __init__(self%s):' % params)
                out.start_block()
                for name, attr in self.attributes.items():
                    out.clear_line()
                    attr.output(out, init=True)
                out.end_block()

            if self.destructor:
                self.destructor.output(out)

            for name, klass in self.classes.items():
                klass.output(out)

            for name, method in self.methods.items():
                method.output(out)
        else:
            out.clear_line()
            out.write('pass')
        out.end_block()


###########################################################################
# Unions
###########################################################################

class Union(Context):
    def __init__(self, context, name):
        super(Union, self).__init__(context=context, name=name)
        # self.module is the module in which this class is defined.
        # self.context is the containing context. This is the same as
        #   self.module in the normal case, but will be the outer class
        #   in the case of a nested class definition.
        self.module = context
        while not isinstance(self.module, Module):
            self.module = self.module.context

        self.superclass = None
        self.attributes = OrderedDict()
        self.methods = OrderedDict()
        self.classes = OrderedDict()

    def add_imports(self, module):
        pass

    def add_attribute(self, attr):
        self.attributes[attr.name] = attr

    def add_method(self, method):
        self.methods[method.name] = method

    def add_to_context(self, context):
        context.add_declaration(self)

    def output(self, out):
        out.clear_major_block()
        out.write("class %s:" % self.name)
        out.start_block()
        if self.attributes or self.classes or self.methods:
            if self.attributes:
                params = ''.join(', %s=None' % name for name in self.attributes.keys())
                out.clear_line()
                out.write('def __init__(self%s):' % params)
                out.start_block()
                for name, attr in self.attributes.items():
                    out.clear_line()
                    attr.output(out, init=True)
                out.end_block()

            for name, klass in self.classes.items():
                klass.output(out)

            for name, method in self.methods.items():
                method.output(out)
        else:
            out.clear_line()
            out.write('pass')

            out.end_block()
        out.end_block()


###########################################################################
# Classes
###########################################################################

class Class(Context):
    def __init__(self, context, name):
        super(Class, self).__init__(context=context, name=name)
        # self.module is the module in which this class is defined.
        # self.context is the containing context. This is the same as
        #   self.module in the normal case, but will be the outer class
        #   in the case of a nested class definition.
        self.module = context
        while not isinstance(self.module, Module):
            self.module = self.module.context

        self.superclass = None
        self.constructors = {}
        self.destructor = None
        self.attributes = OrderedDict()
        self.methods = OrderedDict()
        self.classes = OrderedDict()

    def add_imports(self, module):
        if self.superclass:
            pass

    def add_declaration(self, klass):
        self.classes[klass.name] = klass

    def add_constructor(self, method):
        signature = tuple(p.ctype for p in method.parameters)
        self.constructors[signature] = method

        if len(self.constructors) > 1:
            print("Multiple constructors for class %s (adding [%s])" % (
                    self.name,
                    ','.join(s for s in signature),
                ),
                file=sys.stderr
            )

    def add_destructor(self, method):
        if self.destructor:
            if self.destructor.statements is None:
                self.destructor = method
            else:
                raise Exception("Cannot handle multiple desructors")
        else:
            self.destructor = method

    def add_attribute(self, attr):
        self.attributes[attr.name] = attr

    def add_method(self, method):
        self.methods[method.name] = method

    def add_to_context(self, context):
        context.add_declaration(self)

    def output(self, out):
        out.clear_major_block()
        if self.superclass:
            out.write("class %s(%s):" % (self.name, self.superclass))
        else:
            out.write("class %s:" % self.name)
        out.start_block()
        if self.constructors or self.destructor or self.classes or self.methods:
            for signature, constructor in sorted(self.constructors.items()):
                constructor.output(out)

            if self.destructor:
                self.destructor.output(out)

            for name, klass in self.classes.items():
                klass.output(out)

            for name, method in self.methods.items():
                method.output(out)
        else:
            out.clear_line()
            out.write('pass')
        out.end_block()


###########################################################################
# Class/Struct/Union components
###########################################################################

class Attribute(Declaration):
    def __init__(self, klass, name, value=None):
        super(Attribute, self).__init__(context=klass, name=name)
        self.value = value

    def add_to_context(self, context):
        context.add_attribute(self)

    def add_imports(self, module):
        pass

    def output(self, out, init=False):
        out.write('self.%s = ' % self.name)
        if init:
            if self.value:
                out.write('%s if %s else ' % (self.name, self.name))
                self.value.output(out)
            else:
                out.write(self.name)
        else:
            if self.value:
                self.value.output(out)
            else:
                out.write('None')
        out.clear_line()


class Constructor(Context):
    def __init__(self, klass):
        super(Constructor, self).__init__(context=klass, name=None)
        self.parameters = []
        self.statements = []

    def __repr__(self):
        return '<Constructor %s>' % self.context.full_name

    def add_parameter(self, parameter):
        self.parameters.append(parameter)

    def add_to_context(self, klass):
        self.context.add_constructor(self)

    def add_attribute(self, attr):
        self.context.add_attribute(attr)

    def add_imports(self, module):
        pass

    def add_statement(self, statement):
        self.statements.append(statement)
        statement.add_imports(self.context.module)

    def output(self, out):
        out.clear_minor_block()
        if self.parameters:
            parameters = ', '.join(
                p.name if p.name else 'arg%s' % (i + 1)
                for i, p in enumerate(self.parameters))
            out.write("def __init__(self, %s):" % parameters)
        else:
            out.write("def __init__(self):")
        out.start_block()
        if self.context.attributes or self.statements:
            has_init = False
            for name, attr in self.context.attributes.items():
                if attr.value is not None:
                    out.clear_line()
                    attr.output(out)
                    has_init = True

            if self.statements:
                for statement in self.statements:
                    out.clear_line()
                    statement.output(out)
            elif not has_init:
                out.clear_line()
                out.write('pass')

        else:
            out.clear_line()
            out.write('pass')
        out.end_block()


class Destructor(Context):
    def __init__(self, klass):
        super(Destructor, self).__init__(context=klass, name=None)
        self.parameters = []
        self.statements = None

    def add_to_context(self, klass):
        self.context.add_destructor(self)

    def add_imports(self, module):
        pass

    def add_statement(self, statement):
        if self.statements:
            self.statements.append(statement)
        else:
            self.statements = [statement]
        statement.add_imports(self.context.module)

    def output(self, out):
        out.clear_minor_block()
        out.write("def __del__(self):")
        out.start_block()
        if self.statements:
            for statement in self.statements:
                out.clear_line()
                statement.output(out)
        else:
            out.clear_line()
            out.write('pass')
        out.end_block()


class Method(Context):
    def __init__(self, klass, name, pure_virtual, static):
        super(Method, self).__init__(context=klass, name=name)
        self.parameters = []
        self.statements = None
        self.pure_virtual = pure_virtual
        self.static = static

    def add_parameter(self, parameter):
        self.parameters.append(parameter)

    def add_to_context(self, context):
        self.context.add_method(self)

    def add_imports(self, module):
        if self.statements:
            for statement in self.statements:
                statement.add_imports(module)

    def add_statement(self, statement):
        if self.statements:
            self.statements.append(statement)
        else:
            self.statements = [statement]
        statement.add_imports(self.context.module)

    def output(self, out):
        out.clear_minor_block()
        if self.static:
            out.write("@staticmethod")
            out.clear_line()
            out.write('def %s(' % self.name)
        else:
            out.write('def %s(self' % self.name)

        for i, param in enumerate(self.parameters):
            if i != 0 or not self.static:
                out.write(', ')
            param.output(out)
        out.write('):')

        out.start_block()
        if self.statements:
            for statement in self.statements:
                out.clear_line()
                statement.output(out)
        elif self.pure_virtual:
            out.clear_line()
            out.write('raise NotImplementedError()')
        else:
            out.clear_line()
            out.write('pass')
        out.end_block()


###########################################################################
# Statements
###########################################################################

class Block(Context):
    def __init__(self, context):
        super(Block, self).__init__(context=context, name=None)
        self.statements = []

    def __repr__(self):
        return '<Block>'

    def add_statement(self, statement):
        self.statements.append(statement)

    def add_imports(self, module):
        for statement in self.statements:
            statement.add_imports(module)

    def output(self, out):
        out.start_block()
        if self.statements:
            for statement in self.statements:
                out.clear_line()
                statement.output(out)
        else:
            out.clear_line()
            out.write('pass')
        out.end_block()


class Return(Expression):
    def __init__(self):
        self.value = None

    def add_imports(self, module):
        if self.value:
            self.value.add_imports(module)

    def add_expression(self, expr):
        self.value = expr

    def output(self, out):
        out.write('return')
        if self.value:
            out.write(' ')
            self.value.output(out)
        out.clear_line()


class If(Context):
    def __init__(self, condition, context):
        super(If, self).__init__(context, name=None)
        self.condition = condition
        self.if_true = Block(self)
        self.if_false = None

    def __repr__(self):
        return '<If %s>' % self.condition

    def add_imports(self, module):
        self.condition.add_imports(module)
        self.if_true.add_imports(module)
        if self.if_false:
            self.if_false.add_imports(module)

    def output(self, out, is_elif=False):
        out.clear_line()
        out.write('elif ' if is_elif else 'if ')
        self.condition.output(out)
        out.write(':')

        self.if_true.output(out)

        if self.if_false is not None:
            if isinstance(self.if_false, If):
                self.if_false.output(out, is_elif=True)
            else:
                out.clear_line()
                out.write('else:')
                if isinstance(self.if_false, Block):
                    self.if_false.output(out)
                else:
                    out.clear_line()
                    out.start_block()
                    self.if_false.output(out)
                    out.end_block()


###########################################################################
# References to variables and types
###########################################################################

# A reference to a variable
class VariableReference(Expression):
    def __init__(self, ref, node):
        self.ref = ref
        self.node = node

    def add_imports(self, module):
        parts = self.ref.split('::')

        if len(parts) > 1:
            decl_mod = None
            name_parts = []
            scope_parts = [module.root.name]
            candidate = module.root
            for part in parts:
                new_candidate = candidate[part]
                if decl_mod is None:
                    if isinstance(new_candidate, Module):
                        scope_parts.append(part)
                        candidate = new_candidate
                    else:
                        decl_mod = candidate
                        name_parts.append(part)
                        candidate = new_candidate
                else:
                    name_parts.append(part)
                    candidate = new_candidate

            self.name = name_parts[-1]
            self.module_name = '.'.join(name_parts)
            self.scope = '.'.join(scope_parts)
            # print("NAME", self.name)
            # print("MODULE_NAME", self.module_name)
            # print("SCOPE", self.scope)

            # If the type being referenced isn't from the same module
            # then an import will be required.
            if module.full_name != decl_mod.full_name:
                module.add_import(self.scope, name_parts[0])
        else:
            self.name = self.ref
            self.module_name = self.ref

    def output(self, out):
        out.write(self.module_name)


# A reference to a type
class TypeReference(Expression):
    def __init__(self, ref, node):
        self.ref = ref
        self.node = node

    def __repr__(self):
        return '<TypeReference %s>' % self.ref

    def add_imports(self, module):
        parts = self.ref.split('::')

        decl_mod = None
        name_parts = []
        scope_parts = [module.root.name]
        candidate = module.root
        # print("REF", self.ref)
        for part in parts:
            new_candidate = candidate[part]
            if decl_mod is None:
                if isinstance(new_candidate, Module):
                    scope_parts.append(part)
                    candidate = new_candidate
                else:
                    decl_mod = candidate
                    name_parts.append(part)
                    candidate = new_candidate
            else:
                name_parts.append(part)
                candidate = new_candidate

        self.name = name_parts[-1]
        self.module_name = '.'.join(name_parts)
        self.scope = '.'.join(scope_parts)
        # print("NAME", self.name)
        # print("MODULE_NAME", self.module_name)
        # print("SCOPE", self.scope)

        # If the type being referenced isn't from the same module
        # then an import will be required.
        if module.full_name != decl_mod.full_name:
            module.add_import(self.scope, name_parts[0])

    def output(self, out):
        out.write(self.module_name)


# A reference to a primitive type
class PrimitiveTypeReference(Expression):
    def __init__(self, c_type_name):
        self.name = {
            'unsigned': 'int',
            'unsigned byte': 'int',
            'unsigned short': 'int',
            'unsigned int': 'int',
            'unsigned long': 'int',
            'unsigned long long': 'int',
            'byte': 'int',
            'short': 'int',
            'long': 'int',
            'long long': 'int',
            'double': 'float',
        }.get(c_type_name, c_type_name)

    def add_imports(self, module):
        pass

    def output(self, out):
        out.write(self.name)


# A reference to self.
class SelfReference(Expression):
    def add_imports(self, module):
        pass

    def output(self, out):
        out.write('self')


# A reference to an attribute on a class
class AttributeReference(Expression):
    def __init__(self, instance, attr):
        self.instance = instance
        self.name = attr

    # def add_to_context(self, context):
    #     pass

    def add_imports(self, module):
        self.instance.add_imports(module)

    def output(self, out):
        self.instance.output(out)
        out.write('.%s' % self.name)


###########################################################################
# Literals
###########################################################################

class Literal(Expression):
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return "<%s %s>" % (self.__class__.__name__, self.value)

    def add_imports(self, module):
        pass

    def output(self, out):
        out.write(text(self.value))


class ListLiteral(Expression):
    def __init__(self):
        self.value = []

    def __repr__(self):
        return "<%s %s>" % (self.__class__.__name__, self.value)

    def add_imports(self, module):
        for value in self.value:
            value.add_imports(module)

    def append(self, item):
        self.value.append(item)

    def output(self, out):
        out.write('[')
        for i, item in enumerate(self.value):
            if i != 0:
                out.write(', ')
            item.output(out)
        out.write(']')


###########################################################################
# Expressions
###########################################################################

class UnaryOperation(Expression):
    def __init__(self, op, value):
        self.name = op
        self.value = value

    def add_imports(self, module):
        self.value.add_imports(module)

    def output(self, out, depth=0):
        out.write('    ' * depth)
        python_op = {
            '!': 'not ',
            '~': '~',
        }.get(self.name, self.name)

        out.write(python_op)
        self.value.output(out)

    def clean_argument(self):
        # Strip dereferencing operators
        if self.name == '&':
            return self.value.clean_argument()
        elif self.name == '*':
            return self.value.clean_argument()
        else:
            return self


class BinaryOperation(Expression):
    def __init__(self, lvalue, op, rvalue):
        self.lvalue = lvalue
        self.name = op
        self.rvalue = rvalue

    def __repr__(self):
        return "<%s %s>" % (self.__class__.__name__, self.name)

    def add_imports(self, module):
        self.lvalue.add_imports(module)
        self.rvalue.add_imports(module)

    def output(self, out, depth=0):
        self.lvalue.output(out)
        python_op = {
            # Equality
            '=': ' = ',

            # Arithmetic
            '+': ' + ',
            '-': ' - ',
            '*': ' * ',
            '/': ' / ',
            '%': ' % ',

            # Comparison
            '==': ' == ',
            '!=': ' != ',
            '>': ' > ',
            '<': ' < ',
            '>=': ' >= ',
            '<=': ' <= ',

            # Bitwise
            '&': ' & ',
            '|': ' | ',
            '^': ' ^ ',
            '<<': ' << ',
            '>>': ' >> ',

            # Assignment
            '+=': ' += ',
            '-=': ' -= ',
            '*=': ' *= ',
            '/=': ' /= ',
            '%=': ' %= ',

            '&=': ' &= ',
            '|=': ' |= ',
            '^=': ' ^= ',
            '<<=': ' <<= ',
            '>>=': ' >>= ',

            # Logical
            '&&': ' and ',
            '||': ' or ',

        }.get(self.name, self.name)

        out.write(python_op)
        self.rvalue.output(out)


class ConditionalOperation(Expression):
    def __init__(self, condition, true_result, false_result):
        self.condition = condition
        self.true_result = true_result
        self.false_result = false_result

    def add_imports(self, module):
        self.condition.add_imports(module)
        self.true_result.add_imports(module)
        self.false_result.add_imports(module)

    def output(self, out):
        self.true_result.output(out)
        out.write(' if ')
        self.condition.output(out)
        out.write(' else ')
        self.false_result.output(out)


class Parentheses(Expression):
    def __init__(self, body):
        self.body = body

    def add_imports(self, module):
        self.body.add_imports(module)

    def output(self, out):
        if isinstance(self.body, (BinaryOperation, ConditionalOperation)):
            out.write('(')
            self.body.output(out)
            out.write(')')
        else:
            self.body.output(out)


class ArraySubscript(Expression):
    def __init__(self, value, index):
        self.value = value
        self.index = index

    def add_imports(self, module):
        self.value.add_imports(module)
        self.index.add_imports(module)

    def output(self, out):
        self.value.output(out)
        out.write('[')
        self.index.output(out)
        out.write(']')

    def clean_argument(self):
        return self


class Cast(Expression):
    def __init__(self, typekind, value):
        self.typekind = typekind
        self.value = value

    def __repr__(self):
        return "<Cast %s>" % self.typekind

    def add_imports(self, module):
        self.value.add_imports(module)

    def output(self, out):
        # Primitive types are cast using Python casting.
        # Other types are passed through as ducks.
        if self.typekind == TypeKind.BOOL:
            out.write('bool(')
            self.value.output(out)
            out.write(')')
        elif self.typekind in (
                    TypeKind.CHAR_U,
                    TypeKind.UCHAR,
                    TypeKind.CHAR16,
                    TypeKind.CHAR32,
                    TypeKind.CHAR_S,
                    TypeKind.SCHAR,
                    TypeKind.WCHAR,
                ):
            out.write('str(')
            self.value.output(out)
            out.write(')')
        elif self.typekind in (
                    TypeKind.USHORT,
                    TypeKind.UINT,
                    TypeKind.ULONG,
                    TypeKind.ULONGLONG,
                    TypeKind.UINT128,
                    TypeKind.SHORT,
                    TypeKind.INT,
                    TypeKind.LONG,
                    TypeKind.LONGLONG,
                    TypeKind.INT128,
                ):
            out.write('int(')
            self.value.output(out)
            out.write(')')
        elif self.typekind in (
                    TypeKind.FLOAT,
                    TypeKind.DOUBLE,
                    TypeKind.LONGDOUBLE
                ):
            out.write('float(')
            self.value.output(out)
            out.write(')')
        else:
            self.value.output(out)

    def clean_argument(self):
        return self.value


class Invoke(Expression):
    def __init__(self, fn):
        self.fn = fn
        self.arguments = []

    def __repr__(self):
        return "<Invoke %s>" % self.fn

    def add_argument(self, argument):
        self.arguments.append(argument)

    def add_imports(self, module):
        self.fn.add_imports(module)
        for arg in self.arguments:
            arg.add_imports(module)

    def output(self, out):
        self.fn.output(out)
        out.write('(')
        if self.arguments:
            self.arguments[0].output(out)
            for arg in self.arguments[1:]:
                out.write(', ')
                arg.output(out)
        out.write(')')


class New(Expression):
    def __init__(self, typeref):
        self.typeref = typeref
        self.arguments = []

    def __repr__(self):
        return "<New %s>" % self.typeref.ref

    def add_argument(self, argument):
        self.arguments.append(argument)

    def add_imports(self, module):
        self.typeref.add_imports(module)
        for arg in self.arguments:
            arg.add_imports(module)

    def output(self, out):
        self.typeref.output(out)
        out.write('(')
        if self.arguments:
            self.arguments[0].output(out)
            for arg in self.arguments[1:]:
                out.write(', ')
                arg.output(out)
        out.write(')')