Converters Overview
===================================

**Converters** provides a small in-python DSL / declarative mechanism to define concrete converter classes (inheriting from :py:class:`converters.Converter`) that perform a particular transformation of some python object into another one, allowing you to rename, alter, add, clean etc. fields of objects / maps conveniently, making it easy to work with nested structures and a host of other common cases.

.. note::

   This project is still version 0 and under active development. The API is not fully nailed down yet and so things may change in a back-incomp=atible way before the release of version 1.0.

.. include:: ../../README.rst
   :start-after: readme-section-install-begin
   :end-before: readme-section-install-end

.. include:: ../../README.rst
   :start-after: readme-section-overview-begin
   :end-before: readme-section-overview-end

For full details refer to :py:class:`~converters.Converter`

Contents
--------

.. toctree::

   self
   api
