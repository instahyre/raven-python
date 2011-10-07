# -*- coding: utf-8 -*-

from __future__ import absolute_import

import logging

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.core.signals import got_request_exception
from django.template import TemplateSyntaxError
from django.test import TestCase

from sentry_client.conf import settings
from sentry_client.conf import defaults
from sentry_client.contrib.django import DjangoClient
from sentry_client.contrib.django.models import get_client

settings.CLIENT = 'tests.contrib.django.tests.TempStoreClient'

class TempStoreClient(DjangoClient):
    def __init__(self, *args, **kwargs):
        self.events = []
        super(TempStoreClient, self).__init__(*args, **kwargs)

    def send(self, **kwargs):
        self.events.append(kwargs)

class Settings(object):
    """
    Allows you to define settings that are required for this function to work.

    >>> with Settings(SENTRY_LOGIN_URL='foo'): #doctest: +SKIP
    >>>     print settings.SENTRY_LOGIN_URL #doctest: +SKIP
    """

    NotDefined = object()

    def __init__(self, **overrides):
        self.overrides = overrides
        self._orig = {}

    def __enter__(self):
        for k, v in self.overrides.iteritems():
            self._orig[k] = getattr(django_settings, k, self.NotDefined)
            setattr(django_settings, k, v)
            if k.startswith('SENTRY_'):
                setattr(settings, k.split('SENTRY_', 1)[1], v)

    def __exit__(self, exc_type, exc_value, traceback):
        for k, v in self._orig.iteritems():
            if v is self.NotDefined:
                delattr(django_settings, k)
                if k.startswith('SENTRY_'):
                    k = k.split('SENTRY_', 1)[1]
                    setattr(settings, k, getattr(defaults, k, None))
            else:
                setattr(django_settings, k, v)
                if k.startswith('SENTRY_'):
                    setattr(settings, k.split('SENTRY_', 1)[1], v)

class DjangoClientTest(TestCase):
    ## Fixture setup/teardown
    urls = 'tests.contrib.django.urls'

    def setUp(self):
        self.sentry_client = get_client()

    def test_signal_integration(self):
        try:
            int('hello')
        except:
            got_request_exception.send(sender=self.__class__, request=None)
        else:
            self.fail('Expected an exception.')

        self.assertEquals(len(self.sentry_client.events), 1)
        event = self.sentry_client.events.pop(0)
        self.assertEquals(event['class_name'], 'ValueError')
        self.assertEquals(event['level'], logging.ERROR)
        self.assertEquals(event['message'], u"invalid literal for int() with base 10: 'hello'")
        self.assertEquals(event['view'], 'tests.contrib.django.tests.test_signal_integration')

    def test_view_exception(self):
        self.assertRaises(Exception, self.client.get, reverse('sentry-raise-exc'))

        self.assertEquals(len(self.sentry_client.events), 1)
        event = self.sentry_client.events.pop(0)
        self.assertEquals(event['class_name'], 'Exception')
        self.assertEquals(event['level'], logging.ERROR)
        self.assertEquals(event['message'], 'view exception')
        self.assertEquals(event['view'], 'tests.contrib.django.views.raise_exc')

    def test_user_info(self):
        user = User(username='admin', email='admin@example.com')
        user.set_password('admin')
        user.save()

        self.assertRaises(Exception, self.client.get, reverse('sentry-raise-exc'))

        self.assertEquals(len(self.sentry_client.events), 1)
        event = self.sentry_client.events.pop(0)
        self.assertTrue('user' in event['data']['__sentry__'])
        user_info = event['data']['__sentry__']['user']
        self.assertTrue('is_authenticated' in user_info)
        self.assertFalse(user_info['is_authenticated'])
        self.assertFalse('username' in user_info)
        self.assertFalse('email' in user_info)

        self.assertTrue(self.client.login(username='admin', password='admin'))

        self.assertRaises(Exception, self.client.get, reverse('sentry-raise-exc'))

        self.assertEquals(len(self.sentry_client.events), 1)
        event = self.sentry_client.events.pop(0)
        self.assertTrue('user' in event['data']['__sentry__'])
        user_info = event['data']['__sentry__']['user']
        self.assertTrue('is_authenticated' in user_info)
        self.assertTrue(user_info['is_authenticated'])
        self.assertTrue('username' in user_info)
        self.assertEquals(user_info['username'], 'admin')
        self.assertTrue('email' in user_info)
        self.assertEquals(user_info['email'], 'admin@example.com')

    def test_request_middleware_exception(self):
        with Settings(MIDDLEWARE_CLASSES=['tests.contrib.django.middleware.BrokenRequestMiddleware']):
            self.assertRaises(ImportError, self.client.get, reverse('sentry-raise-exc'))

            self.assertEquals(len(self.sentry_client.events), 1)
            event = self.sentry_client.events.pop(0)

            self.assertEquals(event['class_name'], 'ImportError')
            self.assertEquals(event['level'], logging.ERROR)
            self.assertEquals(event['message'], 'request')
            self.assertEquals(event['view'], 'tests.contrib.django.middleware.process_request')

    # XXX: Django doesn't handle response middleware exceptions (yet)
    # def test_response_middlware_exception(self):
    #     orig = list(django_settings.MIDDLEWARE_CLASSES)
    #     django_settings.MIDDLEWARE_CLASSES = orig + ['tests.middleware.BrokenResponseMiddleware',]
    #
    #     self.assertRaises(ImportError, self.client.get, reverse('sentry'))
    #     self.assertEquals(Message.objects.count(), 1)
    #     self.assertEquals(GroupedMessage.objects.count(), 1)
    #     last = Message.objects.get()
    #     self.assertEquals(last.logger, 'root')
    #     self.assertEquals(last.class_name, 'ImportError')
    #     self.assertEquals(last.level, logging.ERROR)
    #     self.assertEquals(last.message, 'response')
    #     self.assertEquals(last.view, 'tests.middleware.process_response')
    #
    #     django_settings.MIDDLEWARE_CLASSES = orig

    def test_view_middleware_exception(self):
        with Settings(MIDDLEWARE_CLASSES=['tests.contrib.django.middleware.BrokenViewMiddleware']):
            self.assertRaises(ImportError, self.client.get, reverse('sentry-raise-exc'))

            self.assertEquals(len(self.sentry_client.events), 1)
            event = self.sentry_client.events.pop(0)

            self.assertEquals(event['class_name'], 'ImportError')
            self.assertEquals(event['level'], logging.ERROR)
            self.assertEquals(event['message'], 'view')
            self.assertEquals(event['view'], 'tests.contrib.django.middleware.process_view')

    def test_exclude_modules_view(self):
        exclude_paths = self.sentry_client.exclude_paths
        self.sentry_client.exclude_paths = ['tests.views.decorated_raise_exc']
        self.assertRaises(Exception, self.client.get, reverse('sentry-raise-exc-decor'))

        self.assertEquals(len(self.sentry_client.events), 1)
        event = self.sentry_client.events.pop(0)

        self.assertEquals(event['view'], 'tests.contrib.django.views.raise_exc')
        self.sentry_client.exclude_paths = exclude_paths

    def test_include_modules(self):
        include_paths = self.sentry_client.include_paths
        self.sentry_client.include_paths = ['django.shortcuts.get_object_or_404']

        self.assertRaises(Exception, self.client.get, reverse('sentry-django-exc'))

        self.assertEquals(len(self.sentry_client.events), 1)
        event = self.sentry_client.events.pop(0)

        self.assertEquals(event['view'], 'django.shortcuts.get_object_or_404')
        self.sentry_client.include_paths = include_paths

    def test_template_name_as_view(self):
        self.assertRaises(TemplateSyntaxError, self.client.get, reverse('sentry-template-exc'))

        self.assertEquals(len(self.sentry_client.events), 1)
        event = self.sentry_client.events.pop(0)

        self.assertEquals(event['view'], 'error.html')

    # def test_request_in_logging(self):
    #     resp = self.client.get(reverse('sentry-log-request-exc'))
    #     self.assertEquals(resp.status_code, 200)

    #     self.assertEquals(len(self.sentry_client.events), 1)
    #     event = self.sentry_client.events.pop(0)

    #     self.assertEquals(event['view'], 'tests.contrib.django.views.logging_request_exc')
    #     self.assertEquals(event['data']['META']['REMOTE_ADDR'], '127.0.0.1')

    def test_create_from_record_none_exc_info(self):
        # sys.exc_info can return (None, None, None) if no exception is being
        # handled anywhere on the stack. See:
        #  http://docs.python.org/library/sys.html#sys.exc_info
        record = logging.LogRecord(
            'foo',
            logging.INFO,
            pathname=None,
            lineno=None,
            msg='test',
            args=(),
            exc_info=(None, None, None),
        )
        self.sentry_client.create_from_record(record)

        self.assertEquals(len(self.sentry_client.events), 1)
        event = self.sentry_client.events.pop(0)

        self.assertEquals(event['message'], 'test')

    def test_versions(self):
        import sentry_client
        include_paths = self.sentry_client.include_paths
        self.sentry_client.include_paths = ['sentry_client', 'tests']

        self.assertRaises(Exception, self.client.get, reverse('sentry-raise-exc'))

        self.assertEquals(len(self.sentry_client.events), 1)
        event = self.sentry_client.events.pop(0)

        self.assertTrue('versions' in event['data']['__sentry__'])
        self.assertTrue('sentry_client' in event['data']['__sentry__']['versions'])
        self.assertEquals(event['data']['__sentry__']['versions']['sentry_client'], sentry_client.VERSION)
        self.assertTrue('module' in event['data']['__sentry__'])
        self.assertEquals(event['data']['__sentry__']['module'], 'tests')
        self.assertTrue('version' in event['data']['__sentry__'])
        self.assertEquals(event['data']['__sentry__']['version'], '1.0')

        self.sentry_client.include_paths = include_paths

    def test_404_middleware(self):
        with Settings(MIDDLEWARE_CLASSES=['sentry_client.contrib.django.middleware.Sentry404CatchMiddleware']):
            resp = self.client.get('/non-existant-page')
            self.assertEquals(resp.status_code, 404)

            self.assertEquals(len(self.sentry_client.events), 1)
            event = self.sentry_client.events.pop(0)

            self.assertEquals(event['url'], u'http://testserver/non-existant-page')
            self.assertEquals(event['level'], logging.INFO)
            self.assertEquals(event['logger'], 'http404')

    def test_response_error_id_middleware(self):
        # TODO: test with 500s
        with Settings(MIDDLEWARE_CLASSES=['sentry_client.contrib.django.middleware.SentryResponseErrorIdMiddleware', 'sentry_client.contrib.django.middleware.Sentry404CatchMiddleware']):
            resp = self.client.get('/non-existant-page')
            self.assertEquals(resp.status_code, 404)
            headers = dict(resp.items())
            self.assertTrue('X-Sentry-ID' in headers)
            self.assertEquals(len(self.sentry_client.events), 1)
            event = self.sentry_client.events.pop(0)
            self.assertEquals('$'.join([event['message_id'], event['checksum']]), headers['X-Sentry-ID'])

    # def test_get_client(self):
    #     from sentry.client.log import LoggingClient

    #     self.assertEquals(get_client().__class__, Client)
    #     self.assertEquals(get_client(), get_client())

    #     settings.CLIENT = 'sentry.client.log.LoggingClient'

    #     self.assertEquals(get_client().__class__, LoggingClient)
    #     self.assertEquals(get_client(), get_client())

    #     settings.CLIENT = 'sentry.client.base.Client'

