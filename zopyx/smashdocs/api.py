# -*- coding: utf-8 -*-*

################################################################
# zopyx.smashdocs
# (C) 2017, ZOPYX/Andreas Jung, D-72074 Tübingen
################################################################

import datetime
import json
import os
import tempfile
import time
import uuid
import zipfile

import requests
import pkg_resources
import lxml.etree
import six

import jwt
from fs.osfs import OSFS

VERIFY = True

API_MIN_VERSION = '2.6.0.0'

VALIDATE_SDXML = 'SMASHDOCS_VALIDATE' in os.environ


if six.PY2:

    def safe_unicode(s):
        if not isinstance(s, unicode):  # noqa
            return unicode(s, 'utf-8')
        return s

else:

    def safe_unicode(s):
        if not isinstance(s, str):
            return s.decode('utf-8')
        return s


class SmashdocsError(Exception):

    def __init__(self, msg, result=None):
        super(SmashdocsError, self).__init__(msg)
        self.msg = msg
        self.result = result


class CreationFailed(SmashdocsError):
    """ Unable to create a new document """


class UploadError(SmashdocsError):
    """ DOCX upload or import error"""


class ReviewError(SmashdocsError):
    """ Unable to set document to review state """


class ArchiveError(SmashdocsError):
    """ Archiving error """


class UnarchiveError(SmashdocsError):
    """ Unarchiving error """


class DeletionError(SmashdocsError):
    """ Deletion error """


class CopyError(SmashdocsError):
    """ Deletion error """


class DocumentInfoError(SmashdocsError):
    """ Error retrieving document info """


class UpdateMetadataError(SmashdocsError):
    """ Error retrieving document info """


class OpenError(SmashdocsError):
    """ Error opening file """


class ExportError(SmashdocsError):
    """ Export error"""


class UnseenCountError(SmashdocsError):
    """ Unseen counts error """


class ListUnseenChangesError(SmashdocsError):
    """ Unseen counts error """


allowed_sd_roles = ('editor', 'reader', 'approver', 'commentator')


def check_role(role):
    if role not in allowed_sd_roles:
        raise ValueError('Unsupported role in Smashdocs: {0} (allowed: {1})'.format(
            role, allowed_sd_roles))


def check_length(s, max_len):

    if six.PY2:
        if not isinstance(s, unicode):
            raise TypeError('{0} must be unicode'.format(s))
    elif six.PY3:
        if not isinstance(s, str):
            raise TypeError('{0} must be str'.format(s))

    if len(s) > max_len:
        raise ValueError('"{0}" too long (max {1} chars)'.format(s, max_len))


def check_title(s):
    return check_length(s, 200)


def check_description(s):
    return check_length(s, 400)


def check_status(status):
    if status not in ('draft', 'review'):
        raise ValueError('Status must be either "draft" or "review"')


def check_email(s):
    return check_length(s, 150)


def check_firstname(s):
    return check_length(s, 150)


def check_lastname(s):
    return check_length(s, 150)


def check_company(s):
    return check_length(s, 150)


def check_userid(s):
    if not s:
        raise ValueError('"userId" not specified')


def versiontuple(v):
    return tuple(map(int, (v.split("."))))


def check_uuid(uuid_string):
    """ Validate that a UUID string is in fact a valid uuid4.  Happily, the uuid
        module does the actual checking for us.  It is vital that the 'version'
        kwarg be passed to the UUID() call, otherwise any 32-character hex string
        is considered valid.
    """

    try:
        val = uuid.UUID(uuid_string, version=4)
    except ValueError:
        # If it's a value error, then the string
        # is not a valid hex code for a UUID.
        raise ValueError('Invalid UUID {}'.format(uuid_string))

    # If the uuid_string is a valid hex code,
    # but an invalid uuid4,
    # the UUID.__init__ will convert it to a
    # valid uuid4. This is bad for validation purposes.

    if str(val) != uuid_string:
        raise ValueError('Invalid UUID {}'.format(uuid_string))


def check_user_data(user_data):

    check_firstname(user_data.get('firstname'))
    check_lastname(user_data.get('lastname'))
    check_email(user_data.get('email'))
    check_company(user_data.get('company'))
    check_userid(user_data.get('userId'))


class Smashdocs(object):

    # The constructor
    # @param self it's self
    def __init__(self, partner_url, client_id, client_key, group_id=None):
        """ Constructor

            :param partner_url: Smashdocs server URL
            :param client_id: Smashdocs Client ID
            :param client_key: Smashdocs Client Key
            :param group_id: Smashdoc Group ID
        """

        self.partner_url = partner_url
        self.client_id = client_id
        self.client_key = client_key
        self.group_id = group_id

    def __repr__(self):
        return '<Smashdocs {0}>'.format(self.__dict__)

    @property
    def api_min_version(self):
        """ Minmal API version """
        return API_MIN_VERSION

    @property
    def api_min_version_tp(self):
        """ Minmal API version as integer tuple """
        return versiontuple(API_MIN_VERSION)

    def check_response(self, response):
        api_version = response.headers.get('X-Api-Version')
        if api_version:
            api_version_tp = versiontuple(api_version)
            if api_version_tp < self.api_min_version_tp:
                raise SmashdocsError('Partner API version too old ({0}, expected minimal {1})'.format(
                    api_version, self.api_min_version), response)

    def get_token(self):

        if not self.client_key:
            raise ValueError('No client key configured or specified')

        iss = str(uuid.uuid4())
        iat = int(time.mktime(datetime.datetime.now().timetuple()))
        jwt_payload = {
            'iat': iat,
            'iss': iss,
            'jti': str(uuid.uuid4())
        }
        return jwt.encode(payload=jwt_payload, key=self.client_key, algorithm="HS256").decode('utf-8')

    def open_document(self, document_id, role=None, user_data={}):
        """ Open document

            :param document_id: Document id
            :param role: Smashdoc role: editor|reader|approver|commentator
            :param user_data: Dict with user data, see Smashdocs Partner API
        """

        check_role(role)
        check_user_data(user_data)
        check_uuid(document_id)

        headers = {
            'x-client-id': self.client_id,
            'content-type': 'application/json',
            'authorization': 'Bearer ' + self.get_token()
        }
        data = {
            'user': user_data,
            'groupId': self.group_id,
            'userRole': role,
            'sectionHistory': True
        }

        url = self.partner_url + '/partner/documents/{0}'.format(document_id)
        result = requests.post(url, headers=headers,
                               data=json.dumps(data), verify=VERIFY)
        if result.status_code != 200:
            msg = u'Error (HTTP {0}, {1})'.format(
                result.status_code, result.content)
            raise OpenError(msg, result)
        self.check_response(result)
        return result.json()

    def document_info(self, document_id, userId=None):
        """ Get document information

            :param document_id: Smashdocs document id
        """

        check_uuid(document_id)

        headers = {
            'x-client-id': self.client_id,
            'content-type': 'application/json',
            'authorization': 'Bearer ' + self.get_token()
        }

        params = dict()
        if userId:
            params['userId'] = userId

        url = self.partner_url + '/partner/documents/{0}'.format(document_id)
        result = requests.get(url, headers=headers, params=params, verify=VERIFY)
        if result.status_code != 200:
            msg = u'Error (HTTP {0}, {1})'.format(
                result.status_code, result.content)
            raise DocumentInfoError(msg, result)
        self.check_response(result)
        return result.json()

    def upload_document(self, filename, title=None, description=None, role=None, user_data=None, status='draft'):
        """ Upload DOCX document

            :param filename: DOCX filename
            :param title: title of document
            :param description: description of document
            :param role: Smashdoch role: editor|reader|approver|commentator
            :param user_data: dict with user data
            :param status: create new document in draft|review mode
            :rtype: Smashdocs return datastructure (see Partner API docs for details)
        """

        check_title(title)
        check_description(description)
        check_role(role)
        check_status(status)
        check_user_data(user_data)

        if isinstance(filename, str):
            full_filename = os.path.abspath(filename)
            dirname, fn = os.path.split(full_filename)
            dirname = safe_unicode(dirname)
            fn = safe_unicode(fn)
            handle = OSFS(dirname)
        elif isinstance(filename, tuple):
            handle, fn = filename

        headers = {
            'x-client-id': self.client_id,
            'authorization': 'Bearer ' + self.get_token()
        }

        data = {
            'user': user_data,
            'title': safe_unicode(title),
            'description': safe_unicode(description),
            'groupId': self.group_id,
            'userRole': role,
            'status': status,
            'sectionHistory': True
        }

        base, ext = os.path.splitext(fn)
        suffix = 'docx' if ext.lower() == '.docx' else 'zip'
        endpoint = 'word' if ext.lower() == '.docx' else 'sdxml'

        if endpoint == 'sdxml' and filename.endswith('.zip'):
            zf = zipfile.ZipFile(filename)
            sdxml = zf.read('sd.xml')
            zf.close()
            self.validate_sdxml(sdxml)

        with handle.open(fn, 'rb') as fp:
            files = {
                'data': (None, json.dumps(data), 'application/json'),
                'file': ('dummy.{}'.format(suffix), fp, 'application/octet-stream'),
            }

            result = requests.post(
                self.partner_url + '/partner/imports/{0}/upload'.format(endpoint), headers=headers, files=files, verify=VERIFY)

        if result.status_code != 200:
            msg = u'Upload error (HTTP {0}, {1}'.format(
                result.status_code, result.content)
            raise UploadError(msg, result)
        self.check_response(result)
        return result.json()

    def new_document(self, title=None, description=None, role=None, user_data=None, status='draft'):
        """ Create a new document

            :param title: title of document
            :param description: description of document
            :param role: Smashdocs role: editor|reader|approver|commentator
            :param user_data: Smashdocs user data, see Smashdocs Partner API
            :param status: create new document in draft|review mode
        """

        check_title(title)
        check_description(description)
        check_role(role)
        check_status(status)
        check_user_data(user_data)

        headers = {
            'x-client-id': self.client_id,
            'content-type': 'application/json',
            'authorization': 'Bearer ' + self.get_token()
        }

        data = {
            'user': user_data,
            'title': safe_unicode(title),
            'description': safe_unicode(description),
            'groupId': self.group_id,
            'userRole': role,
            'status': status,
            'sectionHistory': True
        }

        result = requests.post(
            self.partner_url + '/partner/documents/create', headers=headers, data=json.dumps(data), verify=VERIFY)
        if result.status_code != 200:
            msg = u'Create error (HTTP {0}, {1}'.format(
                result.status_code, result.content)
            raise CreationFailed(msg, result)
        self.check_response(result)
        return result.json()

    def update_metadata(self, document_id, **kw):
        """ Update metadata"""

        check_uuid(document_id)

        headers = {
            'x-client-id': self.client_id,
            'content-type': 'application/json',
            'authorization': 'Bearer ' + self.get_token()
        }

        url = self.partner_url + \
            '/partner/documents/{0}/metadata'.format(document_id)
        result = requests.post(url, headers=headers,
                               data=json.dumps(kw), verify=VERIFY)
        if result.status_code != 200:
            msg = u'Update metadata error (HTTP {0}, {1}'.format(
                result.status_code, result.content)
            raise UpdateMetadataError(msg, result)
        self.check_response(result)

    def review_document(self, document_id):
        """ Set document by ``document_id into review state``

            :param document_id: Smashdocs document id
            :rtype: None
        """

        check_uuid(document_id)

        headers = {
            'x-client-id': self.client_id,
            'content-type': 'application/json',
            'authorization': 'Bearer ' + self.get_token()
        }
        result = requests.post(
            self.partner_url + '/partner/documents/{0}/review'.format(document_id), headers=headers, verify=VERIFY)
        if result.status_code != 200:
            msg = u'Review state error (HTTP {0}, {1}'.format(
                result.status_code, result.content)
            raise ReviewError(msg, result)
        self.check_response(result)

    def archive_document(self, document_id):
        """ Archive document by ``document_id``

            :param document_id: Smashdocs document id
            :rtype: None
        """

        check_uuid(document_id)

        headers = {
            'x-client-id': self.client_id,
            'content-type': 'application/json',
            'authorization': 'Bearer ' + self.get_token()
        }
        result = requests.post(
            self.partner_url + '/partner/documents/{0}/archive'.format(document_id), headers=headers, verify=VERIFY)
        if result.status_code != 200:
            msg = u'Archive error (HTTP {0}, {1}'.format(
                result.status_code, result.content)
            raise ArchiveError(msg, result)
        self.check_response(result)

    def delete_document(self, document_id):
        """ Delete document by ``document_id``

            :param document_id: Smashdocs document id
            :rtype: None
        """

        check_uuid(document_id)

        headers = {
            'x-client-id': self.client_id,
            'content-type': 'application/json',
            'authorization': 'Bearer ' + self.get_token()
        }

        result = requests.delete(
            self.partner_url + '/partner/documents/{0}'.format(document_id), headers=headers, verify=VERIFY)
        if result.status_code != 200:
            msg = u'DeletionError (HTTP {0}, {1}'.format(
                result.status_code, result.content)
            raise DeletionError(msg, result)
        self.check_response(result)

    def unarchive_document(self, document_id):
        """ Unarchive document by ``document_id``

            :param document_id: Smashdocs document id
            :rtype: None
        """

        check_uuid(document_id)

        headers = {
            'x-client-id': self.client_id,
            'content-type': 'application/json',
            'authorization': 'Bearer ' + self.get_token()
        }

        result = requests.post(
            self.partner_url + '/partner/documents/{0}/unarchive'.format(document_id), headers=headers, verify=VERIFY)
        if result.status_code != 200:
            msg = u'Archive error (HTTP {0}, {1})'.format(
                result.status_code, result.content)
            raise UnarchiveError(msg, result)
        self.check_response(result)

    def duplicate_document(self, document_id, title=None, description=None, creator_id=None):
        """ Duplicate document

            :param documen_id: Smashdocs document id to be duplicated
            :param title: title of new document
            :param description: description of new document
            :param creator_id: Creator id
        """

        check_title(title)
        check_description(description)
        check_uuid(document_id)

        headers = {
            'x-client-id': self.client_id,
            'content-type': 'application/json',
            'authorization': 'Bearer ' + self.get_token(),
        }

        data = {
            'title': title,
            'description': description,
            'creatorUserId': creator_id
        }

        result = requests.post(
            self.partner_url + '/partner/documents/{0}/duplicate'.format(document_id), headers=headers, data=json.dumps(data), verify=VERIFY)
        if result.status_code != 200:
            msg = u'Copy error (HTTP {0}, {1})'.format(
                result.status_code, result.content)
            raise CopyError(msg, result)
        self.check_response(result)
        return result.json()

    def list_templates(self):

        headers = {
            'x-client-id': self.client_id,
            'content-type': 'application/json',
            'authorization': 'Bearer ' + self.get_token(),
        }

        result = requests.get(
            self.partner_url + '/partner/templates/word', headers=headers, verify=VERIFY)
        if result.status_code != 200:
            msg = u'List error (HTTP {0}, {1})'.format(
                result.status_code, result.content)
            raise SmashdocsError(msg, result)
        self.check_response(result)
        return result.json()

    def get_documents(self, group_id=None, user_id=None):
        """ Get all document """

        headers = {
            'x-client-id': self.client_id,
            'content-type': 'application/json',
            'authorization': 'Bearer ' + self.get_token(),
        }

        data = dict()
        if group_id:
            data['groupId'] = group_id
        if user_id:
            data['userId'] = user_id

        result = requests.get(
            self.partner_url + '/partner/documents/list', headers=headers, params=data, verify=VERIFY)
        if result.status_code != 200:
            msg = u'List error (HTTP {0}, {1})'.format(
                result.status_code, result.content)
            raise SmashdocsError(msg, result)
        self.check_response(result)
        return result.json()

    def export_document(self, document_id, user_id, template_id=None, format='docx', settings={}, output_filename=None, mode='final'):
        """ Export document

            :param documen_id: Smashdocs document id to be exported
            :param user_id: user id of the Smashdocs user performing the export
            :param template_id: template UID of a word template (mandatory if format='docx')
            :param format: docx|html|sdxml|parsx
            :param settings: DOCX specific export settings (https://documentation.smashdocs.net/api_guide.html#exporting-documents-to-word)
            :param mode: final|news|allInOne|redlineAndPending
        """

        check_uuid(document_id)

        if format not in ('docx', 'html', 'sdxml', 'parsx'):
            raise ValueError('"format" must be sdxml|html|docx|parsx')

        if format == 'html':
            if mode not in ('final', 'news', 'allInOne', 'redlineAndPending'):
                raise ValueError('"mode" must be final|news|allInOne|redlineAndPending')

        headers = {
            'x-client-id': self.client_id,
            'content-type': 'application/json',
            'authorization': 'Bearer ' + self.get_token(),
        }

        data = {
            'userId': user_id,
        }

        if format == 'docx':
            url = self.partner_url + \
                '/partner/documents/{0}/export/word'.format(document_id)
            data['templateId'] = template_id
            data['settings'] = settings
        elif format == 'sdxml':
            url = self.partner_url + \
                '/partner/documents/{0}/export/sdxml'.format(document_id)
        elif format == 'html':
            data['mode'] = mode
            url = self.partner_url + \
                '/partner/documents/{0}/export/html'.format(document_id)
        elif format == 'parsx':
            url = self.partner_url + \
                '/partner/documents/{0}/export/parsx'.format(document_id)
        else:
            raise ValueError(u'Unsupported format: {}'.format(format))

        result = requests.post(url, headers=headers,
                               data=json.dumps(data), verify=VERIFY)
        if result.status_code != 200:
            msg = u'Export error (HTTP {0}, {1})'.format(
                result.status_code, result.content)
            raise ExportError(msg, result)
        self.check_response(result)

        suffix = format
        if format in ('html', 'sdxml', 'parsx'):
            suffix = 'zip'

        if format == 'sdxml':
            tmp_fn = tempfile.mktemp(suffix='.zip')
            with open(tmp_fn, 'wb') as fp:
                fp.write(result.content)
            zf = zipfile.ZipFile(tmp_fn)
            sdxml = zf.read('sd.xml')
            zf.close()
            os.unlink(tmp_fn)
            self.validate_sdxml(sdxml)

        if not output_filename:
            output_filename = tempfile.mktemp(suffix='.' + suffix)

        if isinstance(output_filename, str):
            full_filename = os.path.abspath(output_filename)
            dirname, fn = os.path.split(full_filename)
            dirname = safe_unicode(dirname)
            fn = safe_unicode(fn)
            handle = OSFS(dirname)
        elif isinstance(output_filename, tuple):
            handle, fn = output_filename

        with handle.open(fn, 'wb') as fp:
            fp.write(result.content)
        return output_filename

    def unseen_count(self, user_id=None):
        """ Get unseen count changes across all documents.

            :param user_id: user id of the Smashdocs user performing the export
        """

        headers = {
            'x-client-id': self.client_id,
            'content-type': 'application/json',
            'authorization': 'Bearer ' + self.get_token(),
        }

        data = {
            'userId': user_id,
        }

        url = self.partner_url + '/partner/documents/unseen/count'
        result = requests.get(url, headers=headers,
                               params=data, verify=VERIFY)
        if result.status_code != 200:
            msg = u'Count unseen error(HTTP {0}, {1})'.format(
                result.status_code, result.content)
            raise CountUnseenError(msg, result)
        self.check_response(result)
        return result.json()


    def list_unseen_changes(self, user_id=None):
        """ List documents with unseen changes 

            :param user_id: user id of the Smashdocs user performing the export
        """

        headers = {
            'x-client-id': self.client_id,
            'content-type': 'application/json',
            'authorization': 'Bearer ' + self.get_token(),
        }

        data = {
            'userId': user_id,
        }

        url = self.partner_url + '/partner/documents/unseen/list'
        result = requests.get(url, headers=headers,
                               params=data, verify=VERIFY)
        if result.status_code != 200:
            msg = u'List unseen changes error(HTTP {0}, {1})'.format(
                result.status_code, result.content)
            raise ListUnseenChangesError(msg, result)
        self.check_response(result)
        return result.json()

    def validate_sdxml(self, xml):
        """ Validate given XML SDXML string against SDXML XSD """

        if not VALIDATE_SDXML:
            return
        schema_text = pkg_resources.resource_string('zopyx.smashdocs', 'sdxml_import.xsd')
        xmlschema_doc = lxml.etree.fromstring(schema_text)
        xmlschema = lxml.etree.XMLSchema(xmlschema_doc)
        doc = lxml.etree.fromstring(xml)
        xmlschema.assertValid(doc)
