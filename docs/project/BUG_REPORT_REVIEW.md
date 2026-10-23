# Bug-report review (manual, 10 tasks)

The spec asks a human to review ten generated bug reports. These ten were drawn with a fixed seed (`scripts/make_review_sheet.py`, seed 2026). For each one, read the report **first**, answer the three questions, then open the hidden bug to check your answers. Tick a box by changing `[ ]` to `[x]`.

Questions:
1. **Reproducible:** could a developer reproduce the problem from this text alone?
2. **No leak:** does it avoid giving away the file, line or code to change?
3. **Realistic:** does it read like something a user might plausibly file?

If a report fails, note why in the comment line. If more than 2 of 10 fail question 1 or 2, tell Claude to tighten `benchgen/issues.py` and regenerate.

## 1. `boltons__floor-negate_condition-003`

_negate_condition, 2 failing test(s), function named in a test: True_

**Report as the agent sees it:**

> Unexpected behaviour in `floor_oor_lower`, `floor_oor_upper`
> 
> On the current checkout some of the library's own tests fail:
> - `tests/test_mathutils.py::test_floor_oor_lower`
> - `tests/test_mathutils.py::test_floor_oor_upper`
> 
> The failures look like this:
> ```
> tests/test_mathutils.py in test_floor_oor_lower
>     with raises(ValueError):
> E   Failed: DID NOT RAISE ValueError
> tests/test_mathutils.py in test_floor_oor_upper
>     assert max(OPTIONS) == floor(OUT_OF_RANGE_UPPER, OPTIONS)
> E   assert 2399 == 2500
> E    +  where 2399 = max([1618, 1378, 166, 1521, 2347, 2016, ...])
> E    +  and   2500 = floor(2500, [1618, 1378, 166, 1521, 2347, 2016, ...])
> ```
> 
> These tests passed before, and I expected them to pass. Could you take a look?

- [ ] Reproducible   - [ ] No leak   - [ ] Realistic
- Comment: 

<details><summary>Show the injected bug (after answering)</summary>

```diff
diff --git a/boltons/mathutils.py b/boltons/mathutils.py
index 9cc530c..e4b31a5 100644
--- a/boltons/mathutils.py
+++ b/boltons/mathutils.py
@@ -111,7 +111,7 @@ def floor(x, options=None):
     2.5
 
     """
-    if options is None:
+    if not options is None:
         return _floor(x)
     options = sorted(options)
```

</details>

## 2. `toolz___get_factory-swap_args-004`

_swap_args, 25 failing test(s), function named in a test: False_

**Report as the agent sees it:**

> Unexpected behaviour in `curried_namespace`, `merge`, `merge_with`
> 
> On the current checkout some of the library's own tests fail:
> - `toolz/tests/test_curried.py::test_curried_namespace`
> - `toolz/tests/test_curried.py::test_merge`
> - `toolz/tests/test_curried.py::test_merge_with`
> - `toolz/tests/test_curried.py::test_merge_with_list`
> - `toolz/tests/test_dicttoolz.py::TestCustomMapping::test_dissoc`
> - `toolz/tests/test_dicttoolz.py::TestCustomMapping::test_factory`
> - `toolz/tests/test_dicttoolz.py::TestCustomMapping::test_merge`
> - `toolz/tests/test_dicttoolz.py::TestCustomMapping::test_merge_iterable_arg`
> - ... and 17 more
> 
> The failures look like this:
> ```
> toolz/tests/test_curried.py in test_curried_namespace
>     namespace.update(toolz.merge(from_toolz, from_exceptions))
> E   TypeError: 'str' object is not callable
> toolz/tests/test_curried.py in test_merge
>     assert merge(factory=lambda: defaultdict(int))({1: 1}) == {1: 1}
> E   assert <function merge at 0xffffac7d6f20> == {1: 1}
> E    +  where <function merge at 0xffffac7d6f20> = <function merge at 0xffffac7d6f20>({1: 1})
> E    +    where <function merge at 0xffffac7d6f20> = merge(factory=<function test_merge.<locals>.<lambda> at 0xffffac78a3e0>)
> toolz/tests/test_curried.py in test_merge_with
>     assert merge_with(sum)({1: 1}, {1: 2}) == {1: 3}
> E   assert <function merge_with at 0xffffac7d6e80> == {1: 3}
> E    +  where <function merge_with at 0xffffac7d6e80> = <function merge_with at 0xffffac7d6e80>({1: 1}, {1: 2})
> E    +    where <function merge_with at 0xffffac7d6e80> = merge_with(sum)
> toolz/tests/test_curried.py in test_merge_with_list
>     assert merge_with(sum, [{'a': 1}, {'a': 2}]) == {'a': 3}
> E   AssertionError: assert <function merge_with at 0xffffac7d6e80> == {'a': 3}
> E    +  where <function merge_with at 0xffffac7d6e80> = merge_with(sum, [{'a': 1}, {'a': 2}])
> toolz/tests/test_dicttoolz.py in test_dissoc
>     assert dissoc(D({"a": 1}), "a", **kw) == D({})
> E   TypeError: dissoc() got an unexpected keyword argument 'factory'
> ```
> 
> These tests passed before, and I expected them to pass. Could you take a look?

- [ ] Reproducible   - [ ] No leak   - [ ] Realistic
- Comment: 

<details><summary>Show the injected bug (after answering)</summary>

```diff
diff --git a/toolz/dicttoolz.py b/toolz/dicttoolz.py
index 457bc26..f7caf77 100644
--- a/toolz/dicttoolz.py
+++ b/toolz/dicttoolz.py
@@ -9,7 +9,7 @@ __all__ = ('merge', 'merge_with', 'valmap', 'keymap', 'itemmap',
 
 
 def _get_factory(f, kwargs):
-    factory = kwargs.pop('factory', dict)
+    factory = kwargs.pop(dict, 'factory')
     if kwargs:
         raise TypeError("{}() got an unexpected keyword argument "
                         "'{}'".format(f.__name__, kwargs.popitem()[0]))
```

</details>

## 3. `toolz__merge_with-bool_op_swap-012`

_bool_op_swap, 5 failing test(s), function named in a test: True_

**Report as the agent sees it:**

> Unexpected behaviour in `merge_with`, `merge_with_iterable_arg`, `merge_with_non_dict_mappings`
> 
> On the current checkout some of the library's own tests fail:
> - `toolz/tests/test_dicttoolz.py::TestCustomMapping::test_merge_with`
> - `toolz/tests/test_dicttoolz.py::TestCustomMapping::test_merge_with_iterable_arg`
> - `toolz/tests/test_dicttoolz.py::TestDefaultDict::test_merge_with`
> - `toolz/tests/test_dicttoolz.py::TestDict::test_merge_with`
> - `toolz/tests/test_dicttoolz.py::test_merge_with_non_dict_mappings`
> 
> The failures look like this:
> ```
> toolz/tests/test_dicttoolz.py in test_merge_with
>     assert merge_with(sum, *dicts, **kw) == D({1: 11, 2: 22})
> E   AttributeError: 'int' object has no attribute 'items'
> toolz/tests/test_dicttoolz.py in test_merge_with_iterable_arg
>     assert merge_with(sum, *dicts, **kw) == D({1: 11, 2: 22})
> E   AttributeError: 'int' object has no attribute 'items'
> toolz/tests/test_dicttoolz.py in test_merge_with
>     assert not merge_with(sum)
> E   IndexError: tuple index out of range
> toolz/tests/test_dicttoolz.py in test_merge_with
>     assert not merge_with(sum)
> E   IndexError: tuple index out of range
> toolz/tests/test_dicttoolz.py in test_merge_with_non_dict_mappings
>     assert merge_with(sum, d) == {1: 1}
> E   AttributeError: 'int' object has no attribute 'items'
> ```
> 
> These tests passed before, and I expected them to pass. Could you take a look?

- [ ] Reproducible   - [ ] No leak   - [ ] Realistic
- Comment: 

<details><summary>Show the injected bug (after answering)</summary>

```diff
diff --git a/toolz/dicttoolz.py b/toolz/dicttoolz.py
index 457bc26..db4532d 100644
--- a/toolz/dicttoolz.py
+++ b/toolz/dicttoolz.py
@@ -55,7 +55,7 @@ def merge_with(func, *dicts, **kwargs):
     See Also:
         merge
     """
-    if len(dicts) == 1 and not isinstance(dicts[0], Mapping):
+    if len(dicts) == 1 or not isinstance(dicts[0], Mapping):
         dicts = dicts[0]
     factory = _get_factory(merge_with, kwargs)
```

</details>

## 4. `toolz__partition_all-bool_op_swap-017`

_bool_op_swap, 1 failing test(s), function named in a test: True_

**Report as the agent sees it:**

> Unexpected behaviour in `partition_all`
> 
> On the current checkout some of the library's own tests fail:
> - `toolz/tests/test_itertoolz.py::test_partition_all`
> 
> The failures look like this:
> ```
> toolz/tests/test_itertoolz.py in test_partition_all
>     assert raises(LookupError, lambda: list(partition_all(5, too_long_list)))
> E   assert False
> E    +  where False = raises(LookupError, <function test_partition_all.<locals>.<lambda> at 0xffff8cbcd4e0>)
> ```
> 
> These tests passed before, and I expected them to pass. Could you take a look?

- [ ] Reproducible   - [ ] No leak   - [ ] Realistic
- Comment: 

<details><summary>Show the injected bug (after answering)</summary>

```diff
diff --git a/toolz/itertoolz.py b/toolz/itertoolz.py
index 05c36cc..c472170 100644
--- a/toolz/itertoolz.py
+++ b/toolz/itertoolz.py
@@ -732,7 +732,7 @@ def partition_all(n, seq):
             # If seq defines __len__, then
             # we can quickly calculate where no_pad starts
             end = len(seq) % n
-            if prev[end - 1] is no_pad or prev[end] is not no_pad:
+            if prev[end - 1] is no_pad and prev[end] is not no_pad:
                 raise LookupError(
                     'The sequence passed to `parition_all` has invalid length'
                 )
```

</details>

## 5. `boltons__find_all_links-off_by_one-002`

_off_by_one, 1 failing test(s), function named in a test: True_

**Report as the agent sees it:**

> Unexpected behaviour in `find_all_links`
> 
> On the current checkout some of the library's own tests fail:
> - `tests/test_urlutils.py::test_find_all_links`
> 
> The failures look like this:
> ```
> tests/test_urlutils.py in test_find_all_links
>     assert link_tokens[0].startswith(prefix)
> E   AssertionError: assert False
> E    +  where False = <built-in method startswith of str object at 0xffffa72c2f10>('a little something before, ')
> E    +    where <built-in method startswith of str object at 0xffffa72c2f10> = 'a little something before,'.startswith
> ```
> 
> These tests passed before, and I expected them to pass. Could you take a look?

- [ ] Reproducible   - [ ] No leak   - [ ] Realistic
- Comment: 

<details><summary>Show the injected bug (after answering)</summary>

```diff
diff --git a/boltons/urlutils.py b/boltons/urlutils.py
index 82f08ce..80c33f9 100644
--- a/boltons/urlutils.py
+++ b/boltons/urlutils.py
@@ -180,7 +180,7 @@ def find_all_links(text, with_text=False, default_scheme='https', schemes=()):
     for match in _FIND_ALL_URL_RE.finditer(text):
         start, end = match.start(1), match.end(1)
         if prev_end < start and with_text:
-            _add(text[prev_end:start])
+            _add(text[prev_end:start - 1])
         prev_end = end
         try:
             cur_url_text = match.group(0)
```

</details>

## 6. `toolz__get-compare_flip-007`

_compare_flip, 1 failing test(s), function named in a test: True_

**Report as the agent sees it:**

> Unexpected behaviour in `get`
> 
> On the current checkout some of the library's own tests fail:
> - `toolz/tests/test_itertoolz.py::test_get`
> 
> The failures look like this:
> ```
> toolz/tests/test_itertoolz.py in test_get
>     assert get('foo', {}, default='bar') == 'bar'
> E   KeyError: 'foo'
> ```
> 
> These tests passed before, and I expected them to pass. Could you take a look?

- [ ] Reproducible   - [ ] No leak   - [ ] Realistic
- Comment: 

<details><summary>Show the injected bug (after answering)</summary>

```diff
diff --git a/toolz/itertoolz.py b/toolz/itertoolz.py
index 05c36cc..365000c 100644
--- a/toolz/itertoolz.py
+++ b/toolz/itertoolz.py
@@ -462,7 +462,7 @@ def get(ind, seq, default=no_default):
         else:
             raise
     except (KeyError, IndexError):  # we know `ind` is not a list
-        if default == no_default:
+        if default != no_default:
             raise
         else:
             return default
```

</details>

## 7. `toolz__topk-bool_op_swap-006`

_bool_op_swap, 2 failing test(s), function named in a test: True_

**Report as the agent sees it:**

> Unexpected behaviour in `topk`, `topk_is_stable`
> 
> On the current checkout some of the library's own tests fail:
> - `toolz/tests/test_itertoolz.py::test_topk`
> - `toolz/tests/test_itertoolz.py::test_topk_is_stable`
> 
> The failures look like this:
> ```
> toolz/tests/test_itertoolz.py in test_topk
>     assert topk(2, [4, 1, 5, 2]) == (5, 4)
> E   TypeError: 'int' object is not subscriptable
> toolz/tests/test_itertoolz.py in test_topk_is_stable
>     assert topk(4, [5, 9, 2, 1, 5, 3], key=lambda x: 1) == (5, 9, 2, 1)
> E   TypeError: 'int' object is not subscriptable
> ```
> 
> These tests passed before, and I expected them to pass. Could you take a look?

- [ ] Reproducible   - [ ] No leak   - [ ] Realistic
- Comment: 

<details><summary>Show the injected bug (after answering)</summary>

```diff
diff --git a/toolz/itertoolz.py b/toolz/itertoolz.py
index 05c36cc..df6eb68 100644
--- a/toolz/itertoolz.py
+++ b/toolz/itertoolz.py
@@ -982,7 +982,7 @@ def topk(k, seq, key=None):
     See also:
         heapq.nlargest
     """
-    if key is not None and not callable(key):
+    if key is not None or not callable(key):
         key = getter(key)
     return tuple(heapq.nlargest(k, seq, key=key))
```

</details>

## 8. `toolz__is_partial_args-change_constant-011`

_change_constant, 8 failing test(s), function named in a test: False_

**Report as the agent sees it:**

> Unexpected behaviour in `curry_kwargs`, `curry_passes_errors`, `func_keyword`
> 
> On the current checkout some of the library's own tests fail:
> - `toolz/tests/test_functoolz.py::test_curry_kwargs`
> - `toolz/tests/test_functoolz.py::test_curry_passes_errors`
> - `toolz/tests/test_inspect_args.py::test_func_keyword`
> - `toolz/tests/test_inspect_args.py::test_introspect_curry_partial_py3`
> - `toolz/tests/test_inspect_args.py::test_introspect_curry_valid_py3`
> - `toolz/tests/test_inspect_args.py::test_is_partial`
> - `toolz/tests/test_inspect_args.py::test_is_valid_curry`
> - `toolz/tests/test_signatures.py::test_is_partial`
> 
> The failures look like this:
> ```
> toolz/tests/test_functoolz.py in test_curry_kwargs
>     assert raises(TypeError, lambda: cg(1, 2))  # pass "b" as arg AND kwarg
> E   assert False
> E    +  where False = raises(TypeError, <function test_curry_kwargs.<locals>.<lambda> at 0xffff88d81080>)
> toolz/tests/test_functoolz.py in test_curry_passes_errors
>     assert raises(TypeError, lambda: f(1, 2, 3))
> E   assert False
> E    +  where False = raises(TypeError, <function test_curry_passes_errors.<locals>.<lambda> at 0xffff881679c0>)
> toolz/tests/test_inspect_args.py in test_func_keyword
>     assert is_partial_args(f, (None,), {'func': None}) is False
> E   AssertionError: assert True is False
> E    +  where True = is_partial_args(<function test_func_keyword.<locals>.f at 0xffff88d80e00>, (None,), {'func': None})
> toolz/tests/test_inspect_args.py in test_introspect_curry_partial_py3
>     test_introspect_curry_valid_py3(check_valid=is_partial_args, incomplete=True)
> toolz/tests/test_inspect_args.py in test_introspect_curry_valid_py3
>     assert check_valid(f, 1, 2, 3, 4) is False
> E   assert True is False
> E    +  where True = <function test_introspect_curry_valid_py3.<locals>.<lambda> at 0xffff88d80b80>(<function func at 0xffff88d809a0>, 1, 2, 3, 4)
> toolz/tests/test_inspect_args.py in test_introspect_curry_valid_py3
>     assert check_valid(f) is False
> E   assert True is False
> E    +  where True = <function test_introspect_curry_valid_py3.<locals>.<lambda> at 0xffff88d80860>(<function func at 0xffff88d80720>)
> ```
> 
> These tests passed before, and I expected them to pass. Could you take a look?

- [ ] Reproducible   - [ ] No leak   - [ ] Realistic
- Comment: 

<details><summary>Show the injected bug (after answering)</summary>

```diff
diff --git a/toolz/functoolz.py b/toolz/functoolz.py
index b4cacac..2d96cf6 100644
--- a/toolz/functoolz.py
+++ b/toolz/functoolz.py
@@ -1002,7 +1002,7 @@ def is_partial_args(func, args, kwargs, sigspec=None):
     try:
         sigspec.bind_partial(*args, **kwargs)
     except TypeError:
-        return False
+        return True
     return True
```

</details>

## 9. `toolz____reduce__-swap_args-015`

_swap_args, 5 failing test(s), function named in a test: False_

**Report as the agent sees it:**

> Unexpected behaviour in `curried_bad_qualname`, `curried_exceptions`, `curried_qualname`
> 
> On the current checkout some of the library's own tests fail:
> - `toolz/tests/test_serialization.py::test_curried_bad_qualname`
> - `toolz/tests/test_serialization.py::test_curried_exceptions`
> - `toolz/tests/test_serialization.py::test_curried_qualname`
> - `toolz/tests/test_serialization.py::test_curry`
> - `toolz/tests/test_serialization.py::test_flip`
> 
> The failures look like this:
> ```
> toolz/tests/test_serialization.py in test_curried_bad_qualname
>     assert raises(pickle.PicklingError, lambda: pickle.dumps(Bad))
> toolz/tests/test_serialization.py in <lambda>
>     assert raises(pickle.PicklingError, lambda: pickle.dumps(Bad))
> E   TypeError: isinstance() arg 2 must be a type, a tuple of types, or a union
> toolz/tests/test_serialization.py in test_curried_exceptions
>     merge = pickle.loads(pickle.dumps(toolz.curried.merge))
> E   TypeError: isinstance() arg 2 must be a type, a tuple of types, or a union
> toolz/tests/test_serialization.py in test_curried_qualname
>     assert preserves_identity(GlobalCurried)
> toolz/tests/test_serialization.py in preserves_identity
>     return pickle.loads(pickle.dumps(obj)) is obj
> E   TypeError: isinstance() arg 2 must be a type, a tuple of types, or a union
> toolz/tests/test_serialization.py in test_curry
>     g = pickle.loads(pickle.dumps(f))
> E   TypeError: isinstance() arg 2 must be a type, a tuple of types, or a union
> toolz/tests/test_serialization.py in test_flip
>     flip = pickle.loads(pickle.dumps(toolz.functoolz.flip))
> E   TypeError: isinstance() arg 2 must be a type, a tuple of types, or a union
> ```
> 
> These tests passed before, and I expected them to pass. Could you take a look?

- [ ] Reproducible   - [ ] No leak   - [ ] Realistic
- Comment: 

<details><summary>Show the injected bug (after answering)</summary>

```diff
diff --git a/toolz/functoolz.py b/toolz/functoolz.py
index b4cacac..b2ce688 100644
--- a/toolz/functoolz.py
+++ b/toolz/functoolz.py
@@ -356,7 +356,7 @@ class curry:
             attrs = []
             obj = import_module(modname)
             for attr in qualname.split('.'):
-                if isinstance(obj, curry):
+                if isinstance(curry, obj):
                     attrs.append('func')
                     obj = obj.func
                 obj = getattr(obj, attr, None)
```

</details>

## 10. `toolz__cons-swap_args-010`

_swap_args, 1 failing test(s), function named in a test: True_

**Report as the agent sees it:**

> Unexpected behaviour in `cons`
> 
> On the current checkout some of the library's own tests fail:
> - `toolz/tests/test_itertoolz.py::test_cons`
> 
> The failures look like this:
> ```
> toolz/tests/test_itertoolz.py in test_cons
>     assert list(cons(1, [2, 3])) == [1, 2, 3]
> E   assert [2, 3, 1] == [1, 2, 3]
> E     At index 0 diff: 2 != 1
> E     Use -v to get more diff
> ```
> 
> These tests passed before, and I expected them to pass. Could you take a look?

- [ ] Reproducible   - [ ] No leak   - [ ] Realistic
- Comment: 

<details><summary>Show the injected bug (after answering)</summary>

```diff
diff --git a/toolz/itertoolz.py b/toolz/itertoolz.py
index 05c36cc..5368782 100644
--- a/toolz/itertoolz.py
+++ b/toolz/itertoolz.py
@@ -514,7 +514,7 @@ def cons(el, seq):
     >>> list(cons(1, [2, 3]))
     [1, 2, 3]
     """
-    return itertools.chain([el], seq)
+    return itertools.chain(seq, [el])
 
 
 def interpose(el, seq):
```

</details>
