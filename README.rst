==============
Rasahub-Humhub
==============

Rasahub-Humhubs implements a connector between Rasahub and `Humhub`_ `Mail`_ .

----

Prerequisites
=============

* Python installed
* Humhub database access (if remote: make sure you have port 3306 opened)
* Bots Humhub User Group created (name 'Bots')
* Assign Bot User to Bots User Group in Humhub Backend

Installation
============

Pypi package
------------

Install via pip:

.. code-block:: bash

  pip install rasahub-humhub


Usage
=====

Create configuration
--------------------

Create file config.yml in working path. Example:

.. code-block:: yaml

  humhub:
    host: '127.0.0.1'
    port: 3306
    dbname: 'humhub'
    dbuser: 'humhubuser'
    dbpasswd: 'humhub123'
    trigger: '!bot'


Command-Line API
----------------

Start rasahub:

.. code-block:: bash

  python -m rasahub


Testing
=======

Prerequisites:

* mysql-server installed
* testing dependencies installed: pip install .[test]

Run Test:

.. code-block:: python

  python -m pytest tests/



* License: MIT
* `PyPi`_ - package installation

.. _Humhub: https://www.humhub.org/de/site/index
.. _Mail: https://github.com/humhub/humhub-modules-mail
.. _PyPi: https://pypi.python.org/pypi/rasahub
