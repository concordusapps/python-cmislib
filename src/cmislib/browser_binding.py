#
#      Licensed to the Apache Software Foundation (ASF) under one
#      or more contributor license agreements.  See the NOTICE file
#      distributed with this work for additional information
#      regarding copyright ownership.  The ASF licenses this file
#      to you under the Apache License, Version 2.0 (the
#      "License"); you may not use this file except in compliance
#      with the License.  You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#      Unless required by applicable law or agreed to in writing,
#      software distributed under the License is distributed on an
#      "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
#      KIND, either express or implied.  See the License for the
#      specific language governing permissions and limitations
#      under the License.
#
"""
Module containing the browser binding-specific objects used to work with a CMIS
provider.
"""
from .cmis_services import RepositoryServiceIfc
from .cmis_services import Binding
from .net import RESTService as Rest
from .exceptions import CmisException, RuntimeException, ObjectNotFoundException
from .domain import CmisId, CmisObject, Repository, Relationship, Policy, ObjectType, Property, Folder, Document, ACL, ACE, ChangeEntry, ResultSet, ChangeEntryResultSet, Rendition
from .util import parsePropValueByType, parseBoolValue
import json
import io
import logging
from urllib.parse import urlencode

CMIS_FORM_TYPE = 'application/x-www-form-urlencoded;charset=utf-8'

moduleLogger = logging.getLogger('cmislib.browser_binding')

class BrowserBinding(Binding):
    def __init__(self, **kwargs):
        self.extArgs = kwargs

    def getRepositoryService(self):
        return RepositoryService()

    def get(self, url, username, password, **kwargs):

        """
        Does a get against the CMIS service. More than likely, you will not
        need to call this method. Instead, let the other objects do it for you.

        For example, if you need to get a specific object by object id, try
        :class:`Repository.getObject`. If you have a path instead of an object
        id, use :class:`Repository.getObjectByPath`. Or, you could start with
        the root folder (:class:`Repository.getRootFolder`) and drill down from
        there.
        """

        # merge the cmis client extended args with the ones that got passed in
        if len(self.extArgs) > 0:
            kwargs.update(self.extArgs)

        resp, content = Rest().get(url,
                            username=username,
                            password=password,
                            **kwargs)
        result = None
        if resp['status'] != '200':
            self._processCommonErrors(resp, url)
        else:
            result = json.loads(content)
        return result

    def post(self, url, payload, contentType, username, password, **kwargs):

        """
        Does a post against the CMIS service. More than likely, you will not
        need to call this method. Instead, let the other objects do it for you.

        For example, to update the properties on an object, you'd call
        :class:`CmisObject.updateProperties`. Or, to check in a document that's
        been checked out, you'd call :class:`Document.checkin` on the PWC.
        """

        # merge the cmis client extended args with the ones that got passed in
        if len(self.extArgs) > 0:
            kwargs.update(self.extArgs)

        result = None
        resp, content = Rest().post(url,
                             payload,
                             contentType,
                             username=username,
                             password=password,
                             **kwargs)
        if resp['status'] != '200' and resp['status'] != '201':
            self._processCommonErrors(resp, url)
        else:
            result = json.loads(content)
        return result


class RepositoryService(RepositoryServiceIfc):
    def getRepository(self, client, repositoryId):
        result = client.binding.get(client.repositoryUrl, client.username, client.password, **client.extArgs)
        
        if repositoryId in result:
            return BrowserRepository(client, result[repositoryId])

        raise ObjectNotFoundException(url=client.repositoryUrl)

    def getRepositories(self, client):
        result = client.binding.get(client.repositoryUrl, client.username, client.password, **client.extArgs)

        repositories = []
        for repo in result.values():
            repositories.append({'repositoryId': repo['repositoryId'],
                                 'repositoryName': repo['repositoryName']})
        return repositories

    def getDefaultRepository(self, client):
        result = client.binding.get(client.repositoryUrl, client.username, client.password, **client.extArgs)
        # instantiate a Repository object with the first workspace
        # element we find
        repository = None
        for repo in result.values():
            repository = BrowserRepository(client, repo)
        return repository


class BrowserCmisObject(object):

    """
    Common ancestor class for other CMIS domain objects such as
    :class:`Document` and :class:`Folder`.
    """

    def __init__(self, cmisClient, repository, objectId=None, data=None, **kwargs):
        """ Constructor """
        self._cmisClient = cmisClient
        self._repository = repository
        self._objectId = objectId
        self._properties = {}
        self._allowableActions = {}
        self.data = data
        self._kwargs = kwargs
        self.logger = logging.getLogger('cmislib.browser_binding.BrowserCmisObject')
        self.logger.info('Creating an instance of CmisObject')

    def __str__(self):
        """To string"""
        return self.getObjectId()

    def _initData(self):

        """
        An internal method used to clear out any member variables that
        might be out of sync if we were to fetch new data from the
        service.
        """

        self._properties = {}
        self._allowableActions = {}

    def reload(self, **kwargs):

        """
        Fetches the latest representation of this object from the CMIS service.
        Some methods, like :class:`^Document.checkout` do this for you.

        If you call reload with a properties filter, the filter will be in
        effect on subsequent calls until the filter argument is changed. To
        reset to the full list of properties, call reload with filter set to
        '*'.
        """

        if kwargs:
            if self._kwargs:
                self._kwargs.update(kwargs)
            else:
                self._kwargs = kwargs

        byObjectIdUrl = self._repository.getRootFolderUrl() + "?objectId=" + self.getObjectId() + "&cmisselector=object"
        self.data = self._cmisClient.binding.get(byObjectIdUrl.encode('utf-8'),
                                                   self._cmisClient.username,
                                                   self._cmisClient.password,
                                                   **kwargs)
        self._initData()

        # if a returnVersion arg was passed in, it is possible we got back
        # a different object ID than the value we started with, so it needs
        # to be cleared out as well
        if 'returnVersion' in kwargs:
            self._objectId = None
    
    def getObjectId(self):

        """
        Returns the object ID for this object.

        >>> doc = resultSet.getResults()[0]
        >>> doc.getObjectId()
        u'workspace://SpacesStore/dc26102b-e312-471b-b2af-91bfb0225339'
        """

        if self._objectId is None:
            if self.data is None:
                self.logger.debug('Both objectId and data were None, reloading')
                self.reload()
            props = self.getProperties()
            self._objectId = CmisId(props['cmis:objectId'])
        return self._objectId

    def getObjectParents(self, **kwargs):
        """
        Gets the parents of this object as a :class:`ResultSet`.

        The following optional arguments are supported:
         - filter
         - includeRelationships
         - renditionFilter
         - includeAllowableActions
         - includeRelativePathSegment
        """
        #TODO add kwargs logic here

        byObjectIdUrl = self._repository.getRootFolderUrl() + "?objectId=" + self.getObjectId() + "&cmisselector=parents"
        result = self._cmisClient.binding.get(byObjectIdUrl.encode('utf-8'),
                                                   self._cmisClient.username,
                                                   self._cmisClient.password,
                                                   **kwargs)
        # return the result set
        return BrowserResultSet(self._cmisClient, self._repository, {'objects': result})

    def getPaths(self):
        """
        Returns the object's paths as a list of strings.
        """
        # see sub-classes for implementation
        pass

    def getAllowableActions(self):

        """
        Returns a dictionary of allowable actions, keyed off of the action name.

        >>> actions = doc.getAllowableActions()
        >>> for a in actions:
        ...     print "%s:%s" % (a,actions[a])
        ...
        canDeleteContentStream:True
        canSetContentStream:True
        canCreateRelationship:True
        canCheckIn:False
        canApplyACL:False
        canDeleteObject:True
        canGetAllVersions:True
        canGetObjectParents:True
        canGetProperties:True
        """

        if self._allowableActions == {}:
            self.reload(includeAllowableActions=True)
            assert 'allowableActions' in self.data, "Expected object data to have an allowableActions key"
            allowableActions = self.data['allowableActions']
            self._allowableActions = allowableActions

        return self._allowableActions

    def getProperties(self):

        """
        Returns a dict of the object's properties. If CMIS returns an
        empty element for a property, the property will be in the
        dict with a value of None.

        >>> props = doc.getProperties()
        >>> for p in props:
        ...     print "%s: %s" % (p, props[p])
        ...
        cmis:contentStreamMimeType: text/html
        cmis:creationDate: 2009-12-15T09:45:35.369-06:00
        cmis:baseTypeId: cmis:document
        cmis:isLatestMajorVersion: false
        cmis:isImmutable: false
        cmis:isMajorVersion: false
        cmis:objectId: workspace://SpacesStore/dc26102b-e312-471b-b2af-91bfb0225339

        The optional filter argument is not yet implemented.
        """

        if self._properties == {}:
            if self.data is None:
                self.reload()
            for prop in self.data['properties'].values():
                self._properties[prop['id']] = parsePropValueByType(prop['value'], prop['type'])
                
        return self._properties

    def getName(self):

        """
        Returns the value of cmis:name from the getProperties() dictionary.
        We don't need a getter for every standard CMIS property, but name
        is a pretty common one so it seems to make sense.

        >>> doc.getName()
        u'system-overview.html'
        """

        return self.getProperties()['cmis:name']

    def updateProperties(self, properties):

        """
        Updates the properties of an object with the properties provided.
        Only provide the set of properties that need to be updated.

        >>> folder = repo.getObjectByPath('/someFolder2')
        >>> folder.getName()
        u'someFolder2'
        >>> props = {'cmis:name': 'someFolderFoo'}
        >>> folder.updateProperties(props)
        <cmislib.model.Folder object at 0x103ab1210>
        >>> folder.getName()
        u'someFolderFoo'

        """

        pass

    def move(self, sourceFolder, targetFolder):

        """
        Moves an object from the source folder to the target folder.

        >>> sub1 = repo.getObjectByPath('/cmislib/sub1')
        >>> sub2 = repo.getObjectByPath('/cmislib/sub2')
        >>> doc = repo.getObjectByPath('/cmislib/sub1/testdoc1')
        >>> doc.move(sub1, sub2)
        """

        pass

    def delete(self, **kwargs):

        """
        Deletes this :class:`CmisObject` from the repository. Note that in the
        case of a :class:`Folder` object, some repositories will refuse to
        delete it if it contains children and some will delete it without
        complaint. If what you really want to do is delete the folder and all
        of its descendants, use :meth:`~Folder.deleteTree` instead.

        >>> folder.delete()

        The optional allVersions argument is supported.
        """

        pass

    def applyPolicy(self, policyId):

        """
        This is not yet implemented.
        """

        pass

    def createRelationship(self, targetObj, relTypeId):

        """
        Creates a relationship between this object and a specified target
        object using the relationship type specified. Returns the new
        :class:`Relationship` object.

        >>> rel = tstDoc1.createRelationship(tstDoc2, 'R:cmiscustom:assoc')
        >>> rel.getProperties()
        {u'cmis:objectId': u'workspace://SpacesStore/271c48dd-6548-4771-a8f5-0de69b7cdc25', u'cmis:creationDate': None, u'cmis:objectTypeId': u'R:cmiscustom:assoc', u'cmis:lastModificationDate': None, u'cmis:targetId': u'workspace://SpacesStore/0ca1aa08-cb49-42e2-8881-53aa8496a1c1', u'cmis:lastModifiedBy': None, u'cmis:baseTypeId': u'cmis:relationship', u'cmis:sourceId': u'workspace://SpacesStore/271c48dd-6548-4771-a8f5-0de69b7cdc25', u'cmis:changeToken': None, u'cmis:createdBy': None}

        """

        pass

    def getRelationships(self, **kwargs):

        """
        Returns a :class:`ResultSet` of :class:`Relationship` objects for each
        relationship where the source is this object.

        >>> rels = tstDoc1.getRelationships()
        >>> len(rels.getResults())
        1
        >>> rel = rels.getResults().values()[0]
        >>> rel.getProperties()
        {u'cmis:objectId': u'workspace://SpacesStore/271c48dd-6548-4771-a8f5-0de69b7cdc25', u'cmis:creationDate': None, u'cmis:objectTypeId': u'R:cmiscustom:assoc', u'cmis:lastModificationDate': None, u'cmis:targetId': u'workspace://SpacesStore/0ca1aa08-cb49-42e2-8881-53aa8496a1c1', u'cmis:lastModifiedBy': None, u'cmis:baseTypeId': u'cmis:relationship', u'cmis:sourceId': u'workspace://SpacesStore/271c48dd-6548-4771-a8f5-0de69b7cdc25', u'cmis:changeToken': None, u'cmis:createdBy': None}

        The following optional arguments are supported:
         - includeSubRelationshipTypes
         - relationshipDirection
         - typeId
         - maxItems
         - skipCount
         - filter
         - includeAllowableActions
        """

        pass

    def removePolicy(self, policyId):

        """
        This is not yet implemented.
        """

        pass

    def getAppliedPolicies(self):

        """
        This is not yet implemented.
        """

        pass

    def getACL(self):

        """
        Repository.getCapabilities['ACL'] must return manage or discover.

        >>> acl = folder.getACL()
        >>> acl.getEntries()
        {u'GROUP_EVERYONE': <cmislib.model.ACE object at 0x10071a8d0>, 'jdoe': <cmislib.model.ACE object at 0x10071a590>}

        The optional onlyBasicPermissions argument is currently not supported.
        """

        if self._repository.getCapabilities()['ACL']:
            # if the ACL capability is discover or manage, this must be
            # supported
            aclUrl = self._repository.getRootFolderUrl() + "?cmisselector=object&objectId=" + self.getObjectId() + "&includeACL=true"
            result = self._cmisClient.binding.get(aclUrl.encode('utf-8'),
                                              self._cmisClient.username,
                                              self._cmisClient.password)
            return BrowserACL(data=result['acl'])
        else:
            raise NotSupportedException

    def applyACL(self, acl):

        """
        Updates the object with the provided :class:`ACL`.
        Repository.getCapabilities['ACL'] must return manage to invoke this
        call.

        >>> acl = folder.getACL()
        >>> acl.addEntry(ACE('jdoe', 'cmis:write', 'true'))
        >>> acl.getEntries()
        {u'GROUP_EVERYONE': <cmislib.model.ACE object at 0x10071a8d0>, 'jdoe': <cmislib.model.ACE object at 0x10071a590>}
        """

        pass

    allowableActions = property(getAllowableActions)
    name = property(getName)
    id = property(getObjectId)
    properties = property(getProperties)
    ACL = property(getACL)


class BrowserRepository(object):
    """
    Represents a CMIS repository. Will lazily populate itself by
    calling the repository CMIS service URL.

    You must pass in an instance of a CmisClient when creating an
    instance of this class.
    """

    def __init__(self, cmisClient, data=None):
        """ Constructor """
        self._cmisClient = cmisClient
        self.data = data
        self._repositoryId = None
        self._repositoryName = None
        self._repositoryInfo = {}
        self._capabilities = {}
        self._permDefs = {}
        self._permMap = {}
        self._permissions = None
        self._propagation = None
        self.logger = logging.getLogger('cmislib.browser_binding.BrowserRepository')
        self.logger.info('Creating an instance of Repository')

    def __str__(self):
        """To string"""
        return self.getRepositoryName()

    def _initData(self):
        """
        This method clears out any local variables that would be out of sync
        when data is re-fetched from the server.
        """
        self._repositoryId = None
        self._repositoryName = None
        self._repositoryInfo = {}
        self._capabilities = {}
        self._uriTemplates = {}
        self._permDefs = {}
        self._permMap = {}
        self._permissions = None
        self._propagation = None

    def reload(self):
        """
        This method will re-fetch the repository's XML data from the CMIS
        repository.
        """

        pass

    def getRepositoryId(self):

        """
        Returns this repository's unique identifier

        >>> repo = client.getDefaultRepository()
        >>> repo.getRepositoryId()
        u'83beb297-a6fa-4ac5-844b-98c871c0eea9'
        """

        if self._repositoryId is None:
            if self.data is None:
                self.reload()
            self._repositoryId = self.data['repositoryId']
        return self._repositoryId
    
    def getRepositoryName(self):

        """
        Returns this repository's name

        >>> repo = client.getDefaultRepository()
        >>> repo.getRepositoryName()
        u'Main Repository'
        """

        if self._repositoryName is None:
            if self.data is None:
                self.reload()
            self._repositoryName = self.data['repositoryName']
        return self._repositoryName

    def getRepositoryInfo(self):

        """
        Returns a dict of repository information.

        >>> repo = client.getDefaultRepository()>>> repo.getRepositoryName()
        u'Main Repository'
        >>> info = repo.getRepositoryInfo()
        >>> for k,v in info.items():
        ...     print "%s:%s" % (k,v)
        ...
        cmisSpecificationTitle:Version 1.0 Committee Draft 04
        cmisVersionSupported:1.0
        repositoryDescription:None
        productVersion:3.2.0 (r2 2440)
        rootFolderId:workspace://SpacesStore/aa1ecedf-9551-49c5-831a-0502bb43f348
        repositoryId:83beb297-a6fa-4ac5-844b-98c871c0eea9
        repositoryName:Main Repository
        vendorName:Alfresco
        productName:Alfresco Repository (Community)
        """

        if not self._repositoryInfo:
            if self.data is None:
                self.reload()
            repoInfo = {'repositoryId': self.data['repositoryId'], 'repositoryName': self.data['repositoryName'],
                        'resositoryDescription': self.data['repositoryDescription'],
                        'vendorName': self.data['vendorName'], 'productName': self.data['productName'],
                        'productVersion': self.data['productVersion'], 'rootFolderId': self.data['rootFolderId'],
                        'latestChangeLogToken': self.data['latestChangeLogToken'],
                        'cmisVersionSupported': self.data['cmisVersionSupported'],
                        'thinClientURI': self.data['thinClientURI'],
                        'changesIncomplete': self.data['changesIncomplete'],
                        'changesOnType': self.data['changesOnType'],
                        'principalIdAnonymous': self.data['principalIdAnonymous'],
                        'principalIdAnyone': self.data['principalIdAnyone']}
            if 'extendedFeatures' in self.data:
                repoInfo['extendedFeatures'] = self.data['extendedFeatures']
            self._repositoryInfo = repoInfo
        return self._repositoryInfo

    def getRootFolderUrl(self):
        if self.data is None:
            self.reload()
        return self.data['rootFolderUrl']

    def getRepositoryUrl(self):
        if self.data is None:
            self.reload()
        return self.data['repositoryUrl']

    def getObjectByPath(self, path, **kwargs):

        """
        Returns an object given the path to the object.

        >>> doc = repo.getObjectByPath('/jeff test/sample-b.pdf')
        >>> doc.getTitle()
        u'sample-b.pdf'

        The following optional arguments are not currently supported:
         - filter
         - includeAllowableActions
        """

        if kwargs:
            if self._kwargs:
                self._kwargs.update(kwargs)
            else:
                self._kwargs = kwargs

        byPathUrl = self.getRootFolderUrl() + path + "?cmisselector=object"
        result = self._cmisClient.binding.get(byPathUrl.encode('utf-8'),
                                                   self._cmisClient.username,
                                                   self._cmisClient.password,
                                                   **kwargs)
        return getSpecializedObject(BrowserCmisObject(self._cmisClient, self, data=result, **kwargs), **kwargs)

    def getSupportedPermissions(self):
        """
        Returns the value of the cmis:supportedPermissions element. Valid
        values are:

         - basic: indicates that the CMIS Basic permissions are supported
         - repository: indicates that repository specific permissions are supported
         - both: indicates that both CMIS basic permissions and repository specific permissions are supported

        >>> repo.supportedPermissions
        u'both'
        """

        if not self.getCapabilities()['ACL']:
            raise NotSupportedException(messages.NO_ACL_SUPPORT)

        if not self._permissions:
            if self.data is None:
                self.reload()
            if 'aclCapabilities' in self.data:
                if 'supportedPermissions' in self.data['aclCapabilities']:
                    self._permissions = self.data['aclCapabilities']['supportedPermissions']
        return self._permissions

    def getPermissionDefinitions(self):

        """
        Returns a dictionary of permission definitions for this repository. The
        key is the permission string or technical name of the permission
        and the value is the permission description.

        >>> for permDef in repo.permissionDefinitions:
        ...     print permDef
        ...
        cmis:all
        {http://www.alfresco.org/model/system/1.0}base.LinkChildren
        {http://www.alfresco.org/model/content/1.0}folder.Consumer
        {http://www.alfresco.org/model/security/1.0}All.All
        {http://www.alfresco.org/model/system/1.0}base.CreateAssociations
        {http://www.alfresco.org/model/system/1.0}base.FullControl
        {http://www.alfresco.org/model/system/1.0}base.AddChildren
        {http://www.alfresco.org/model/system/1.0}base.ReadAssociations
        {http://www.alfresco.org/model/content/1.0}folder.Editor
        {http://www.alfresco.org/model/content/1.0}cmobject.Editor
        {http://www.alfresco.org/model/system/1.0}base.DeleteAssociations
        cmis:read
        cmis:write
        """
        #TODO need to implement
        pass

    def getPermissionMap(self):

        """
        Returns a dictionary representing the permission mapping table where
        each key is a permission key string and each value is a list of one or
        more permissions the principal must have to perform the operation.

        >>> for (k,v) in repo.permissionMap.items():
        ...     print 'To do this: %s, you must have these perms:' % k
        ...     for perm in v:
        ...             print perm
        ...
        To do this: canCreateFolder.Folder, you must have these perms:
        cmis:all
        {http://www.alfresco.org/model/system/1.0}base.CreateChildren
        To do this: canAddToFolder.Folder, you must have these perms:
        cmis:all
        {http://www.alfresco.org/model/system/1.0}base.CreateChildren
        To do this: canDelete.Object, you must have these perms:
        cmis:all
        {http://www.alfresco.org/model/system/1.0}base.DeleteNode
        To do this: canCheckin.Document, you must have these perms:
        cmis:all
        {http://www.alfresco.org/model/content/1.0}lockable.CheckIn
        """
        #TODO need to implement
        pass

    def getPropagation(self):

        """
        Returns the value of the cmis:propagation element. Valid values are:
          - objectonly: indicates that the repository is able to apply ACEs
            without changing the ACLs of other objects
          - propagate: indicates that the repository is able to apply ACEs to a
            given object and propagate this change to all inheriting objects

        >>> repo.propagation
        u'propagate'
        """
        #TODO need to implement
        pass

    def getCapabilities(self):

        """
        Returns a dict of repository capabilities.

        >>> caps = repo.getCapabilities()
        >>> for k,v in caps.items():
        ...     print "%s:%s" % (k,v)
        ...
        PWCUpdatable:True
        VersionSpecificFiling:False
        Join:None
        ContentStreamUpdatability:anytime
        AllVersionsSearchable:False
        Renditions:None
        Multifiling:True
        GetFolderTree:True
        GetDescendants:True
        ACL:None
        PWCSearchable:True
        Query:bothcombined
        Unfiling:False
        Changes:None
        """

        if not self._capabilities:
            if self.data is None:
                self.reload()
            caps = {}
            if 'capabilities' in self.data:
                for cap in list(self.data['capabilities'].keys()):
                    key = cap.replace('capability', '')
                    caps[key] = self.data['capabilities'][cap]
                self._capabilities = caps
        return self._capabilities

    def getRootFolder(self):
        """
        Returns the root folder of the repository

        >>> root = repo.getRootFolder()
        >>> root.getObjectId()
        u'workspace://SpacesStore/aa1ecedf-9551-49c5-831a-0502bb43f348'
        """

        # get the root folder id
        rootFolderId = self.getRepositoryInfo()['rootFolderId']
        # instantiate a Folder object using the ID
        folder = BrowserFolder(self._cmisClient, self, rootFolderId)
        # return it
        return folder

    def getFolder(self, folderId):

        """
        Returns a :class:`Folder` object for a specified folderId

        >>> someFolder = repo.getFolder('workspace://SpacesStore/aa1ecedf-9551-49c5-831a-0502bb43f348')
        >>> someFolder.getObjectId()
        u'workspace://SpacesStore/aa1ecedf-9551-49c5-831a-0502bb43f348'
        """

        retObject = self.getObject(folderId)
        return BrowserFolder(self._cmisClient, self, data=retObject.data)

    def getTypeChildren(self,
                        typeId=None):

        """
        Returns a list of :class:`ObjectType` objects corresponding to the
        child types of the type specified by the typeId.

        If no typeId is provided, the result will be the same as calling
        `self.getTypeDefinitions`

        These optional arguments are current unsupported:
         - includePropertyDefinitions
         - maxItems
         - skipCount

        >>> baseTypes = repo.getTypeChildren()
        >>> for baseType in baseTypes:
        ...     print baseType.getTypeId()
        ...
        cmis:folder
        cmis:relationship
        cmis:document
        cmis:policy
        """

        pass

    def getTypeDescendants(self, typeId=None, **kwargs):

        """
        Returns a list of :class:`ObjectType` objects corresponding to the
        descendant types of the type specified by the typeId.

        If no typeId is provided, the repository's "typesdescendants" URL
        will be called to determine the list of descendant types.

        >>> allTypes = repo.getTypeDescendants()
        >>> for aType in allTypes:
        ...     print aType.getTypeId()
        ...
        cmis:folder
        F:cm:systemfolder
        F:act:savedactionfolder
        F:app:configurations
        F:fm:forums
        F:wcm:avmfolder
        F:wcm:avmplainfolder
        F:wca:webfolder
        F:wcm:avmlayeredfolder
        F:st:site
        F:app:glossary
        F:fm:topic

        These optional arguments are supported:
         - depth
         - includePropertyDefinitions

        >>> types = alfRepo.getTypeDescendants('cmis:folder')
        >>> len(types)
        17
        >>> types = alfRepo.getTypeDescendants('cmis:folder', depth=1)
        >>> len(types)
        12
        >>> types = alfRepo.getTypeDescendants('cmis:folder', depth=2)
        >>> len(types)
        17
        """

        pass

    def getTypeDefinitions(self, **kwargs):

        """
        Returns a list of :class:`ObjectType` objects representing
        the base types in the repository.

        >>> baseTypes = repo.getTypeDefinitions()
        >>> for baseType in baseTypes:
        ...     print baseType.getTypeId()
        ...
        cmis:folder
        cmis:relationship
        cmis:document
        cmis:policy
        """

        typesUrl = self.getRepositoryUrl() + "?cmisselector=typeChildren"
        result = self._cmisClient.binding.get(typesUrl,
                                                   self._cmisClient.username,
                                                   self._cmisClient.password,
                                                   **kwargs)
        types = []
        for res in result['types']:
            objectType = BrowserObjectType(self._cmisClient,
                                    self,
                                    data=res)
            types.append(objectType)
        # return the result
        return types

    def getTypeDefinition(self, typeId):

        """
        Returns an :class:`ObjectType` object for the specified object type id.

        >>> folderType = repo.getTypeDefinition('cmis:folder')
        """

        pass

    def getCheckedOutDocs(self, **kwargs):

        """
        Returns a ResultSet of :class:`CmisObject` objects that
        are currently checked out.

        >>> rs = repo.getCheckedOutDocs()
        >>> len(rs.getResults())
        2
        >>> for doc in repo.getCheckedOutDocs().getResults():
        ...     doc.getTitle()
        ...
        u'sample-a (Working Copy).pdf'
        u'sample-b (Working Copy).pdf'

        These optional arguments are supported:
         - folderId
         - maxItems
         - skipCount
         - orderBy
         - filter
         - includeRelationships
         - renditionFilter
         - includeAllowableActions
        """

        pass

    def getUnfiledDocs(self, **kwargs):

        """
        Returns a ResultSet of :class:`CmisObject` objects that
        are currently unfiled.

        >>> rs = repo.getUnfiledDocs()
        >>> len(rs.getResults())
        2
        >>> for doc in repo.getUnfiledDocs().getResults():
        ...     doc.getTitle()
        ...
        u'sample-a.pdf'
        u'sample-b.pdf'

        These optional arguments are supported:
         - folderId
         - maxItems
         - skipCount
         - orderBy
         - filter
         - includeRelationships
         - renditionFilter
         - includeAllowableActions
        """

        pass

    def getObject(self,
                  objectId,
                  **kwargs):

        """
        Returns an object given the specified object ID.

        >>> doc = repo.getObject('workspace://SpacesStore/f0c8b90f-bec0-4405-8b9c-2ab570589808')
        >>> doc.getTitle()
        u'sample-b.pdf'

        The following optional arguments are supported:
         - returnVersion
         - filter
         - includeRelationships
         - includePolicyIds
         - renditionFilter
         - includeACL
         - includeAllowableActions
        """

        return getSpecializedObject(BrowserCmisObject(self._cmisClient, self, objectId, **kwargs), **kwargs)

    def query(self, statement, **kwargs):

        """
        Returns a list of :class:`CmisObject` objects based on the CMIS
        Query Language passed in as the statement. The actual objects
        returned will be instances of the appropriate child class based
        on the object's base type ID.

        In order for the results to be properly instantiated as objects,
        make sure you include 'cmis:objectId' as one of the fields in
        your select statement, or just use "SELECT \*".

        If you want the search results to automatically be instantiated with
        the appropriate sub-class of :class:`CmisObject` you must either
        include cmis:baseTypeId as one of the fields in your select statement
        or just use "SELECT \*".

        >>> q = "select * from cmis:document where cmis:name like '%test%'"
        >>> resultSet = repo.query(q)
        >>> len(resultSet.getResults())
        1
        >>> resultSet.hasNext()
        False

        The following optional arguments are supported:
         - searchAllVersions
         - includeRelationships
         - renditionFilter
         - includeAllowableActions
         - maxItems
         - skipCount

        >>> q = 'select * from cmis:document'
        >>> rs = repo.query(q)
        >>> len(rs.getResults())
        148
        >>> rs = repo.query(q, maxItems='5')
        >>> len(rs.getResults())
        5
        >>> rs.hasNext()
        True
        """

        # build the CMIS query XML that we're going to POST
        queryUrl = self.getRepositoryUrl() + "?cmisaction=query&q=" + statement

        # do the POST
        result = self._cmisClient.binding.post(queryUrl.encode('utf-8'),
                                               self._cmisClient.username,
                                               self._cmisClient.password,
                                               None,
                                               CMIS_FORM_TYPE,
                                               **kwargs)

        # return the result set
        return BrowserResultSet(self._cmisClient, self, result)


    def getContentChanges(self, **kwargs):

        """
        Returns a :class:`ResultSet` containing :class:`ChangeEntry` objects.

        >>> for changeEntry in rs:
        ...     changeEntry.objectId
        ...     changeEntry.id
        ...     changeEntry.changeType
        ...     changeEntry.changeTime
        ...
        'workspace://SpacesStore/0e2dc775-16b7-4634-9e54-2417a196829b'
        u'urn:uuid:0e2dc775-16b7-4634-9e54-2417a196829b'
        u'created'
        datetime.datetime(2010, 2, 11, 12, 55, 14)
        'workspace://SpacesStore/bd768f9f-99a7-4033-828d-5b13f96c6923'
        u'urn:uuid:bd768f9f-99a7-4033-828d-5b13f96c6923'
        u'updated'
        datetime.datetime(2010, 2, 11, 12, 55, 13)
        'workspace://SpacesStore/572c2cac-6b26-4cd8-91ad-b2931fe5b3fb'
        u'urn:uuid:572c2cac-6b26-4cd8-91ad-b2931fe5b3fb'
        u'updated'

        The following optional arguments are supported:
         - changeLogToken
         - includeProperties
         - includePolicyIDs
         - includeACL
         - maxItems

        You can get the latest change log token by inspecting the repository
        info via :meth:`Repository.getRepositoryInfo`.

        >>> repo.info['latestChangeLogToken']
        u'2692'
        >>> rs = repo.getContentChanges(changeLogToken='2692')
        >>> len(rs)
        1
        >>> rs[0].id
        u'urn:uuid:8e88f694-93ef-44c5-9f70-f12fff824be9'
        >>> rs[0].changeType
        u'updated'
        >>> rs[0].changeTime
        datetime.datetime(2010, 2, 16, 20, 6, 37)
        """

        pass

    def createDocumentFromString(self,
                                 name,
                                 properties={},
                                 parentFolder=None,
                                 contentString=None,
                                 contentType=None,
                                 contentEncoding=None):

        """
        Creates a new document setting the content to the string provided. If
        the repository supports unfiled objects, you do not have to pass in
        a parent :class:`Folder` otherwise it is required.

        This method is essentially a convenience method that wraps your string
        with a StringIO and then calls createDocument.

        >>> repo.createDocumentFromString('testdoc5', parentFolder=testFolder, contentString='Hello, World!', contentType='text/plain')
        <cmislib.model.Document object at 0x101352ed0>
        """

        pass

    def createDocument(self,
                       name,
                       properties={},
                       parentFolder=None,
                       contentFile=None,
                       contentType=None,
                       contentEncoding=None):

        """
        Creates a new :class:`Document` object. If the repository
        supports unfiled objects, you do not have to pass in
        a parent :class:`Folder` otherwise it is required.

        To create a document with an associated contentFile, pass in a
        File object. The method will attempt to guess the appropriate content
        type and encoding based on the file. To specify it yourself, pass them
        in via the contentType and contentEncoding arguments.

        >>> f = open('sample-a.pdf', 'rb')
        >>> doc = folder.createDocument('sample-a.pdf', contentFile=f)
        <cmislib.model.Document object at 0x105be5e10>
        >>> f.close()
        >>> doc.getTitle()
        u'sample-a.pdf'

        The following optional arguments are not currently supported:
         - versioningState
         - policies
         - addACEs
         - removeACEs
        """

        pass

    def createDocumentFromSource(self,
                                 sourceId,
                                 properties={},
                                 parentFolder=None):
        """
        This is not yet implemented.

        The following optional arguments are not yet supported:
         - versioningState
         - policies
         - addACEs
         - removeACEs
        """

        pass

    def createFolder(self,
                     parentFolder,
                     name,
                     properties={},
                     **kwargs):

        """
        Creates a new :class:`Folder` object in the specified parentFolder.

        >>> root = repo.getRootFolder()
        >>> folder = repo.createFolder(root, 'someFolder2')
        >>> folder.getTitle()
        u'someFolder2'
        >>> folder.getObjectId()
        u'workspace://SpacesStore/2224a63c-350b-438c-be72-8f425e79ce1f'

        The following optional arguments are not yet supported:
         - policies
         - addACEs
         - removeACEs
        """

        return parentFolder.createFolder(name, properties, **kwargs)

    def createRelationship(self, sourceObj, targetObj, relType):
        """
        Creates a relationship of the specific type between a source object
        and a target object and returns the new :class:`Relationship` object.

        The following optional arguments are not currently supported:
         - policies
         - addACEs
         - removeACEs
        """

        pass

    def createPolicy(self, properties):
        """
        This has not yet been implemented.

        The following optional arguments are not currently supported:
         - folderId
         - policies
         - addACEs
         - removeACEs
        """

        pass

    capabilities = property(getCapabilities)
    id = property(getRepositoryId)
    info = property(getRepositoryInfo)
    name = property(getRepositoryName)
    rootFolder = property(getRootFolder)
    permissionDefinitions = property(getPermissionDefinitions)
    permissionMap = property(getPermissionMap)
    propagation = property(getPropagation)
    supportedPermissions = property(getSupportedPermissions)


class BrowserResultSet(object):

    """
    Represents a paged result set.
    """

    def __init__(self, cmisClient, repository, data):
        """ Constructor """
        self._cmisClient = cmisClient
        self._repository = repository
        self._data = data
        self._results = []
        self.logger = logging.getLogger('cmislib.model.browser_binding.BrowserResultSet')
        self.logger.info('Creating an instance of ResultSet')

    def __iter__(self):
        """ Iterator for the result set """
        return iter(self.getResults())

    def __getitem__(self, index):
        """ Getter for the result set """
        return self.getResults()[index]

    def __len__(self):
        """ Len method for the result set """
        return len(self.getResults())

    def reload(self):

        """
        Re-invokes the self link for the current set of results.

        >>> resultSet = repo.getCollection(CHECKED_OUT_COLL)
        >>> resultSet.reload()

        """

        pass

    def getResults(self):

        """
        Returns the results that were fetched and cached by the get*Page call.

        >>> resultSet = repo.getCheckedOutDocs()
        >>> resultSet.hasNext()
        False
        >>> for result in resultSet.getResults():
        ...     result
        ...
        <cmislib.model.Document object at 0x104851810>
        """

        if self._results:
            return self._results

        if self._data:
            entries = []
            for obj in self._data['objects']:
                cmisObject = getSpecializedObject(BrowserCmisObject(self._cmisClient,
                                                                    self._repository,
                                                                    data=obj['object']))
                entries.append(cmisObject)

            self._results = entries

        return self._results

    def hasObject(self, objectId):

        """
        Returns True if the specified objectId is found in the list of results,
        otherwise returns False.
        """

        pass

    def getFirst(self):

        """
        Returns the first page of results as a dictionary of
        :class:`CmisObject` objects or its appropriate sub-type. This only
        works when the server returns a "first" link. Not all of them do.

        >>> resultSet.hasFirst()
        True
        >>> results = resultSet.getFirst()
        >>> for result in results:
        ...     result
        ...
        <cmislib.model.Document object at 0x10480bc90>
        """

        pass

    def getPrev(self):

        """
        Returns the prev page of results as a dictionary of
        :class:`CmisObject` objects or its appropriate sub-type. This only
        works when the server returns a "prev" link. Not all of them do.
        >>> resultSet.hasPrev()
        True
        >>> results = resultSet.getPrev()
        >>> for result in results:
        ...     result
        ...
        <cmislib.model.Document object at 0x10480bc90>
        """

        pass

    def getNext(self):

        """
        Returns the next page of results as a dictionary of
        :class:`CmisObject` objects or its appropriate sub-type.
        >>> resultSet.hasNext()
        True
        >>> results = resultSet.getNext()
        >>> for result in results:
        ...     result
        ...
        <cmislib.model.Document object at 0x10480bc90>
        """

        pass

    def getLast(self):

        """
        Returns the last page of results as a dictionary of
        :class:`CmisObject` objects or its appropriate sub-type. This only
        works when the server is returning a "last" link. Not all of them do.

        >>> resultSet.hasLast()
        True
        >>> results = resultSet.getLast()
        >>> for result in results:
        ...     result
        ...
        <cmislib.model.Document object at 0x10480bc90>
        """

        pass

    def hasNext(self):

        """
        Returns True if this page contains a next link.

        >>> resultSet.hasNext()
        True
        """

        pass

    def hasPrev(self):

        """
        Returns True if this page contains a prev link. Not all CMIS providers
        implement prev links consistently.

        >>> resultSet.hasPrev()
        True
        """

        pass

    def hasFirst(self):

        """
        Returns True if this page contains a first link. Not all CMIS providers
        implement first links consistently.

        >>> resultSet.hasFirst()
        True
        """

        pass

    def hasLast(self):

        """
        Returns True if this page contains a last link. Not all CMIS providers
        implement last links consistently.

        >>> resultSet.hasLast()
        True
        """

        pass


class BrowserDocument(BrowserCmisObject):

    """
    An object typically associated with file content.
    """

    def checkout(self):

        """
        Performs a checkout on the :class:`Document` and returns the
        Private Working Copy (PWC), which is also an instance of
        :class:`Document`

        >>> doc.getObjectId()
        u'workspace://SpacesStore/f0c8b90f-bec0-4405-8b9c-2ab570589808;1.0'
        >>> doc.isCheckedOut()
        False
        >>> pwc = doc.checkout()
        >>> doc.isCheckedOut()
        True
        """

        pass

    def cancelCheckout(self):
        """
        Cancels the checkout of this object by retrieving the Private Working
        Copy (PWC) and then deleting it. After the PWC is deleted, this object
        will be reloaded to update properties related to a checkout.

        >>> doc.isCheckedOut()
        True
        >>> doc.cancelCheckout()
        >>> doc.isCheckedOut()
        False
        """

        pass

    def getPrivateWorkingCopy(self):

        """
        Retrieves the object using the object ID in the property:
        cmis:versionSeriesCheckedOutId then uses getObject to instantiate
        the object.

        >>> doc.isCheckedOut()
        False
        >>> doc.checkout()
        <cmislib.model.Document object at 0x103a25ad0>
        >>> pwc = doc.getPrivateWorkingCopy()
        >>> pwc.getTitle()
        u'sample-b (Working Copy).pdf'
        """

        # reloading the document just to make sure we've got the latest
        # and greatest PWC ID
        self.reload()
        pwcDocId = self.getProperties()['cmis:versionSeriesCheckedOutId']
        if pwcDocId:
            return self._repository.getObject(pwcDocId)

    def isCheckedOut(self):

        """
        Returns true if the document is checked out.

        >>> doc.isCheckedOut()
        True
        >>> doc.cancelCheckout()
        >>> doc.isCheckedOut()
        False
        """

        # reloading the document just to make sure we've got the latest
        # and greatest checked out prop
        self.reload()
        return self.getProperties()['cmis:isVersionSeriesCheckedOut']

    def getCheckedOutBy(self):

        """
        Returns the ID who currently has the document checked out.
        >>> pwc = doc.checkout()
        >>> pwc.getCheckedOutBy()
        u'admin'
        """

        # reloading the document just to make sure we've got the latest
        # and greatest checked out prop
        self.reload()
        return self.getProperties()['cmis:versionSeriesCheckedOutBy']

    def checkin(self, checkinComment=None, **kwargs):

        """
        Checks in this :class:`Document` which must be a private
        working copy (PWC).

        >>> doc.isCheckedOut()
        False
        >>> pwc = doc.checkout()
        >>> doc.isCheckedOut()
        True
        >>> pwc.checkin()
        <cmislib.model.Document object at 0x103a8ae90>
        >>> doc.isCheckedOut()
        False

        The following optional arguments are supported:
         - major
         - properties
         - contentStream
         - policies
         - addACEs
         - removeACEs
        """

        pass

    def getLatestVersion(self, **kwargs):

        """
        Returns a :class:`Document` object representing the latest version in
        the version series.

        The following optional arguments are supported:
         - major
         - filter
         - includeRelationships
         - includePolicyIds
         - renditionFilter
         - includeACL
         - includeAllowableActions

        >>> latestDoc = doc.getLatestVersion()
        >>> latestDoc.getProperties()['cmis:versionLabel']
        u'2.1'
        >>> latestDoc = doc.getLatestVersion(major='false')
        >>> latestDoc.getProperties()['cmis:versionLabel']
        u'2.1'
        >>> latestDoc = doc.getLatestVersion(major='true')
        >>> latestDoc.getProperties()['cmis:versionLabel']
        u'2.0'
        """

        pass

    def getPropertiesOfLatestVersion(self, **kwargs):

        """
        Like :class:`^CmisObject.getProperties`, returns a dict of properties
        from the latest version of this object in the version series.

        The optional major and filter arguments are supported.
        """

        pass

    def getAllVersions(self, **kwargs):

        """
        Returns a :class:`ResultSet` of document objects for the entire
        version history of this object, including any PWC's.

        The optional filter and includeAllowableActions are
        supported.
        """

        # get the version history link
        versionsUrl = self._repository.getRootFolderUrl() + '?cmisselector=versions' + '&objectId=' + self.getObjectId()

        # invoke the URL
        result = self._cmisClient.binding.get(versionsUrl.encode('utf-8'),
                                              self._cmisClient.username,
                                              self._cmisClient.password,
                                              **kwargs)

        # return the result set
        return BrowserResultSet(self._cmisClient, self._repository, {'objects': result})

    def getContentStream(self):

        """
        Returns the CMIS service response from invoking the 'enclosure' link.

        >>> doc.getName()
        u'sample-b.pdf'
        >>> o = open('tmp.pdf', 'wb')
        >>> result = doc.getContentStream()
        >>> o.write(result.read())
        >>> result.close()
        >>> o.close()
        >>> import os.path
        >>> os.path.getsize('tmp.pdf')
        117248

        The optional streamId argument is not yet supported.
        """

        if not self.getAllowableActions()['canGetContentStream']:
            return None

        contentUrl = self._repository.getRootFolderUrl() + "?objectId=" + self.getObjectId() + "&selector=content"
        result, content = Rest().get(contentUrl.encode('utf-8'),
                                              self._cmisClient.username,
                                              self._cmisClient.password,
                                              **self._cmisClient.extArgs)
        if result['status'] != '200':
            raise CmisException(result['status'])
        return io.StringIO(content)

    def setContentStream(self, contentFile, contentType=None):

        """
        Sets the content stream on this object.

        The following optional arguments are not yet supported:
         - overwriteFlag=None
        """

        pass

    def deleteContentStream(self):

        """
        Delete's the content stream associated with this object.
        """

        pass

    def getRenditions(self):

        """
        Returns an array of :class:`Rendition` objects. The repository
        must support the Renditions capability.

        The following optional arguments are not currently supported:
         - renditionFilter
         - maxItems
         - skipCount
        """

        pass

    checkedOut = property(isCheckedOut)

    def getPaths(self):
        """
        Returns the Document's paths by asking for the parents with the
        includeRelativePathSegment flag set to true, then concats the value
        of cmis:path with the relativePathSegment.
        """

        byObjectIdUrl = self._repository.getRootFolderUrl() + "?objectId=" + self.getObjectId() + "&cmisselector=parents"
        result = self._cmisClient.binding.get(byObjectIdUrl.encode('utf-8'),
                                                   self._cmisClient.username,
                                                   self._cmisClient.password)
        
        paths = []
        rs = self.getObjectParents()
        #TODO why is the call to getObjectParents() made if it isn't used?
        for res in result:
            path = res['object']['properties']['cmis:path']['value']
            relativePathSegment = res['relativePathSegment']

            # concat with a slash
            # add it to the list
            paths.append(path + '/' + relativePathSegment)

        return paths


class BrowserFolder(BrowserCmisObject):

    """
    A container object that can hold other :class:`CmisObject` objects
    """

    def createFolder(self, name, properties={}, **kwargs):

        """
        Creates a new :class:`Folder` using the properties provided.
        Right now I expect a property called 'cmis:name' but I don't
        complain if it isn't there (although the CMIS provider will). If a
        cmis:name property isn't provided, the value passed in to the name
        argument will be used.

        To specify a custom folder type, pass in a property called
        cmis:objectTypeId set to the :class:`CmisId` representing the type ID
        of the instance you want to create. If you do not pass in an object
        type ID, an instance of 'cmis:folder' will be created.

        >>> subFolder = folder.createFolder('someSubfolder')
        >>> subFolder.getName()
        u'someSubfolder'

        The following optional arguments are not supported:
         - policies
         - addACEs
         - removeACEs
        """

        # get the root folder URL
        createFolderUrl = self._repository.getRootFolderUrl()

        props = {"objectId" : self.id,
                 "cmisaction" : "createFolder",
                 "propertyId[0]" : "cmis:name",
                 "propertyValue[0]" : name}

        props["propertyId[1]"] = "cmis:objectTypeId"
        if 'cmis:objectTypeId' in properties:
            props["propertyValue[1]"] = properties['cmis:objectTypeId']
        else:
            props["propertyValue[1]"] = "cmis:folder"

        propCount = 2
        for prop in properties:
            props["propertyId[%s]" % propCount] = prop.key
            props["propertyValue[%s]" % propCount] = prop
            propCount += 1

        # invoke the URL
        result = self._cmisClient.binding.post(createFolderUrl.encode('utf-8'),
                                               urlencode(props),
                                               'application/x-www-form-urlencoded',
                                               self._cmisClient.username,
                                               self._cmisClient.password,
                                               **kwargs)

        # return the result set
        return BrowserFolder(self._cmisClient, self._repository, data=result)

    def createDocumentFromString(self,
                                 name,
                                 properties={},
                                 contentString=None,
                                 contentType=None,
                                 contentEncoding=None):

        """
        Creates a new document setting the content to the string provided. If
        the repository supports unfiled objects, you do not have to pass in
        a parent :class:`Folder` otherwise it is required.

        This method is essentially a convenience method that wraps your string
        with a StringIO and then calls createDocument.

        >>> testFolder.createDocumentFromString('testdoc3', contentString='hello, world', contentType='text/plain')
        """

        pass

    def createDocument(self, name, properties={}, contentFile=None,
            contentType=None, contentEncoding=None):

        """
        Creates a new Document object in the repository using
        the properties provided.

        Right now this is basically the same as createFolder,
        but this deals with contentStreams. The common logic should
        probably be moved to CmisObject.createObject.

        The method will attempt to guess the appropriate content
        type and encoding based on the file. To specify it yourself, pass them
        in via the contentType and contentEncoding arguments.

        >>> f = open('250px-Cmis_logo.png', 'rb')
        >>> subFolder.createDocument('logo.png', contentFile=f)
        <cmislib.model.Document object at 0x10410fa10>
        >>> f.close()

        If you wanted to set one or more properties when creating the doc, pass
        in a dict, like this:

        >>> props = {'cmis:someProp':'someVal'}
        >>> f = open('250px-Cmis_logo.png', 'rb')
        >>> subFolder.createDocument('logo.png', props, contentFile=f)
        <cmislib.model.Document object at 0x10410fa10>
        >>> f.close()

        To specify a custom object type, pass in a property called
        cmis:objectTypeId set to the :class:`CmisId` representing the type ID
        of the instance you want to create. If you do not pass in an object
        type ID, an instance of 'cmis:document' will be created.

        The following optional arguments are not yet supported:
         - versioningState
         - policies
         - addACEs
         - removeACEs
        """

        pass

    def getChildren(self, **kwargs):

        """
        Returns a paged :class:`ResultSet`. The result set contains a list of
        :class:`CmisObject` objects for each child of the Folder. The actual
        type of the object returned depends on the object's CMIS base type id.
        For example, the method might return a list that contains both
        :class:`Document` objects and :class:`Folder` objects.

        >>> childrenRS = subFolder.getChildren()
        >>> children = childrenRS.getResults()

        The following optional arguments are supported:
         - maxItems
         - skipCount
         - orderBy
         - filter
         - includeRelationships
         - renditionFilter
         - includeAllowableActions
         - includePathSegment
        """

        byObjectIdUrl = self._repository.getRootFolderUrl() + "?objectId=" + self.getObjectId() + "&cmisselector=children"
        result = self._cmisClient.binding.get(byObjectIdUrl.encode('utf-8'),
                                                   self._cmisClient.username,
                                                   self._cmisClient.password,
                                                   **kwargs)
        # return the result set
        return BrowserResultSet(self._cmisClient, self._repository, result)

    def getDescendants(self, **kwargs):

        """
        Gets the descendants of this folder. The descendants are returned as
        a paged :class:`ResultSet` object. The result set contains a list of
        :class:`CmisObject` objects where the actual type of each object
        returned will vary depending on the object's base type id. For example,
        the method might return a list that contains both :class:`Document`
        objects and :class:`Folder` objects.

        The following optional argument is supported:
         - depth. Use depth=-1 for all descendants, which is the default if no
           depth is specified.

        >>> resultSet = folder.getDescendants()
        >>> len(resultSet.getResults())
        105
        >>> resultSet = folder.getDescendants(depth=1)
        >>> len(resultSet.getResults())
        103

        The following optional arguments *may* also work but haven't been
        tested:

         - filter
         - includeRelationships
         - renditionFilter
         - includeAllowableActions
         - includePathSegment

        """

        pass

    def getTree(self, **kwargs):

        """
        Unlike :class:`Folder.getChildren` or :class:`Folder.getDescendants`,
        this method returns only the descendant objects that are folders. The
        results do not include the current folder.

        The following optional arguments are supported:
         - depth
         - filter
         - includeRelationships
         - renditionFilter
         - includeAllowableActions
         - includePathSegment

         >>> rs = folder.getTree(depth='2')
         >>> len(rs.getResults())
         3
         >>> for folder in rs.getResults().values():
         ...     folder.getTitle()
         ...
         u'subfolder2'
         u'parent test folder'
         u'subfolder'
        """

        pass

    def getParent(self):

        """
        The optional filter argument is not yet supported.
        """
        if 'cmis:parentId' in self.properties and self.properties['cmis:parentId'] is not None:
            return BrowserFolder(self._cmisClient, self._repository, objectId=self.properties['cmis:parentId'])

    def deleteTree(self, **kwargs):

        """
        Deletes the folder and all of its descendant objects.

        >>> resultSet = subFolder.getDescendants()
        >>> len(resultSet.getResults())
        2
        >>> subFolder.deleteTree()

        The following optional arguments are supported:
         - allVersions
         - unfileObjects
         - continueOnFailure
        """

        pass

    def addObject(self, cmisObject, **kwargs):

        """
        Adds the specified object as a child of this object. No new object is
        created. The repository must support multifiling for this to work.

        >>> sub1 = repo.getObjectByPath("/cmislib/sub1")
        >>> sub2 = repo.getObjectByPath("/cmislib/sub2")
        >>> doc = sub1.createDocument("testdoc1")
        >>> len(sub1.getChildren())
        1
        >>> len(sub2.getChildren())
        0
        >>> sub2.addObject(doc)
        >>> len(sub2.getChildren())
        1
        >>> sub2.getChildren()[0].name
        u'testdoc1'

        The following optional arguments are supported:
         - allVersions
        """

        pass

    def removeObject(self, cmisObject):

        """
        Removes the specified object from this folder. The repository must
        support unfiling for this to work.
        """

        pass
    
    def getPaths(self):
        """
        Returns the paths as a list of strings. The spec says folders cannot
        be multi-filed, so this should always be one value. We return a list
        to be symmetric with the same method in :class:`Document`.
        """

        return [self.properties['cmis:path']]


class BrowserRelationship(CmisObject):

    """
    Defines a relationship object between two :class:`CmisObjects` objects
    """

    def getSourceId(self):

        """
        Returns the :class:`CmisId` on the source side of the relationship.
        """
        #TODO need to implement
        pass

    def getTargetId(self):

        """
        Returns the :class:`CmisId` on the target side of the relationship.
        """
        #TODO need to implement
        pass

    def getSource(self):

        """
        Returns an instance of the appropriate child-type of :class:`CmisObject`
        for the source side of the relationship.
        """
        #TODO need to implement
        pass

    def getTarget(self):

        """
        Returns an instance of the appropriate child-type of :class:`CmisObject`
        for the target side of the relationship.
        """
        #TODO need to implement
        pass

    sourceId = property(getSourceId)
    targetId = property(getTargetId)
    source = property(getSource)
    target = property(getTarget)


class BrowserPolicy(CmisObject):

    """
    An arbirary object that can 'applied' to objects that the
    repository identifies as being 'controllable'.
    """

    pass


class BrowserObjectType(object):

    """
    Represents the CMIS object type such as 'cmis:document' or 'cmis:folder'.
    Contains metadata about the type.
    """

    def __init__(self, cmisClient, repository, typeId=None, data=None):
        """ Constructor """
        self._cmisClient = cmisClient
        self._repository = repository
        self._kwargs = None
        self._typeId = typeId
        self.data = data
        self.logger = logging.getLogger('cmislib.browser_binding.BrowserObjectType')
        self.logger.info('Creating an instance of BrowserObjectType')

    def __str__(self):
        """To string"""
        return self.getTypeId()

    def getTypeId(self):

        """
        Returns the type ID for this object.

        >>> docType = repo.getTypeDefinition('cmis:document')
        >>> docType.getTypeId()
        'cmis:document'
        """

        if self._typeId is None:
            if self.data is None:
                self.reload()
            self._typeId = CmisId(self.data['id'])

        return self._typeId

    def getLocalName(self):
        """Getter for cmis:localName"""
        if self.data is None:
            self.reload()
        return self.data['localName']

    def getLocalNamespace(self):
        """Getter for cmis:localNamespace"""
        if self.data is None:
            self.reload()
        return self.data['localNamespace']

    def getDisplayName(self):
        """Getter for cmis:displayName"""

        if self.data is None:
            self.reload()
        return self.data['displayName']

    def getQueryName(self):
        """Getter for cmis:queryName"""
        if self.data is None:
            self.reload()
        return self.data['queryName']

    def getDescription(self):
        """Getter for cmis:description"""
        if self.data is None:
            self.reload()
        return self.data['description']

    def getBaseId(self):
        """Getter for cmis:baseId"""
        if self.data is None:
            self.reload()
        return self.data['baseId']

    def isCreatable(self):
        """Getter for cmis:creatable"""
        if self.data is None:
            self.reload()
        return self.data['creatable']

    def isFileable(self):
        """Getter for cmis:fileable"""
        if self.data is None:
            self.reload()
        return self.data['fileable']

    def isQueryable(self):
        """Getter for cmis:queryable"""
        if self.data is None:
            self.reload()
        return self.data['queryable']

    def isFulltextIndexed(self):
        """Getter for cmis:fulltextIndexed"""

        if self.data is None:
            self.reload()
        return self.data['fulltextIndexed']

    def isIncludedInSupertypeQuery(self):
        """Getter for cmis:includedInSupertypeQuery"""

        if self.data is None:
            self.reload()
        return self.data['includedInSupertypeQuery']

    def isControllablePolicy(self):
        """Getter for cmis:controllablePolicy"""

        if self.data is None:
            self.reload()
        return self.data['controllablePolicy']

    def isControllableACL(self):
        """Getter for cmis:controllableACL"""

        if self.data is None:
            self.reload()
        return self.data['controllableACL']

    def getProperties(self):

        """
        Returns a list of :class:`Property` objects representing each property
        defined for this type.

        >>> objType = repo.getTypeDefinition('cmis:relationship')
        >>> for prop in objType.properties:
        ...    print 'Id:%s' % prop.id
        ...    print 'Cardinality:%s' % prop.cardinality
        ...    print 'Description:%s' % prop.description
        ...    print 'Display name:%s' % prop.displayName
        ...    print 'Local name:%s' % prop.localName
        ...    print 'Local namespace:%s' % prop.localNamespace
        ...    print 'Property type:%s' % prop.propertyType
        ...    print 'Query name:%s' % prop.queryName
        ...    print 'Updatability:%s' % prop.updatability
        ...    print 'Inherited:%s' % prop.inherited
        ...    print 'Orderable:%s' % prop.orderable
        ...    print 'Queryable:%s' % prop.queryable
        ...    print 'Required:%s' % prop.required
        ...    print 'Open choice:%s' % prop.openChoice
        """

        if self.data is None or 'propertyDefinitions' not in self.data:
            self.reload()
        props = {}
        for prop in list(self.data['propertyDefinitions'].keys()):
            props[prop] = BrowserProperty(self.data['propertyDefinitions'][prop])
        return props

    def reload(self, **kwargs):
        """
        This method will reload the object's data from the CMIS service.
        """
        if kwargs:
            if self._kwargs:
                self._kwargs.update(kwargs)
            else:
                self._kwargs = kwargs

        typesUrl = self._repository.getRepositoryUrl()
        kwargs['cmisselector'] = 'typeDefinition'
        kwargs['typeId'] = self.getTypeId()
        result = self._cmisClient.binding.get(typesUrl,
                                                   self._cmisClient.username,
                                                   self._cmisClient.password,
                                                   **kwargs)
        self.data = result

    id = property(getTypeId)
    localName = property(getLocalName)
    localNamespace = property(getLocalNamespace)
    displayName = property(getDisplayName)
    queryName = property(getQueryName)
    description = property(getDescription)
    baseId = property(getBaseId)
    creatable = property(isCreatable)
    fileable = property(isFileable)
    queryable = property(isQueryable)
    fulltextIndexed = property(isFulltextIndexed)
    includedInSupertypeQuery = property(isIncludedInSupertypeQuery)
    controllablePolicy = property(isControllablePolicy)
    controllableACL = property(isControllableACL)
    properties = property(getProperties)


class BrowserProperty(object):

    """
    This class represents an attribute or property definition of an object
    type.
    """

    def __init__(self, data):
        """Constructor"""
        self.data = data
        self.logger = logging.getLogger('cmislib.browser_binding.BrowserProperty')
        self.logger.info('Creating an instance of BrowserProperty')

    def __str__(self):
        """To string"""
        return self.getId()

    def getId(self):
        """Getter for cmis:id"""
        return self.data['id']

    def getLocalName(self):
        """Getter for cmis:localName"""
        return self.data['localName']

    def getLocalNamespace(self):
        """Getter for cmis:localNamespace"""
        return self.data['localNamespace']

    def getDisplayName(self):
        """Getter for cmis:displayName"""
        return self.data['displayName']

    def getQueryName(self):
        """Getter for cmis:queryName"""
        return self.data['queryName']

    def getDescription(self):
        """Getter for cmis:description"""
        return self.data['description']

    def getPropertyType(self):
        """Getter for cmis:propertyType"""
        return self.data['propertyType']

    def getCardinality(self):
        """Getter for cmis:cardinality"""
        return self.data['cardinality']

    def getUpdatability(self):
        """Getter for cmis:updatability"""
        return self.data['updatability']

    def isInherited(self):
        """Getter for cmis:inherited"""
        return self.data['inherited']

    def isRequired(self):
        """Getter for cmis:required"""
        return self.data['required']

    def isQueryable(self):
        """Getter for cmis:queryable"""
        return self.data['queryable']

    def isOrderable(self):
        """Getter for cmis:orderable"""
        return self.data['orderable']

    def isOpenChoice(self):
        """Getter for cmis:openChoice"""
        return self.data['openChoice']

    id = property(getId)
    localName = property(getLocalName)
    localNamespace = property(getLocalNamespace)
    displayName = property(getDisplayName)
    queryName = property(getQueryName)
    description = property(getDescription)
    propertyType = property(getPropertyType)
    cardinality = property(getCardinality)
    updatability = property(getUpdatability)
    inherited = property(isInherited)
    required = property(isRequired)
    queryable = property(isQueryable)
    orderable = property(isOrderable)
    openChoice = property(isOpenChoice)


class BrowserACL(object):

    """
    Represents the Access Control List for an object.
    """

    def __init__(self, aceList=None, data=None):

        """
        Constructor. Pass in either a list of :class:`ACE` objects or the XML
        representation of the ACL. If you have only one ACE, don't worry about
        the list--the constructor will convert it to a list for you.
        """

        if aceList:
            self._entries = aceList
        else:
            self._entries = {}
        if data:
            self._data = data
            self._entries = self._getEntriesFromData()
        else:
            self._data = None

        self.logger = logging.getLogger('cmislib.browser_binding.BrowserACL')
        self.logger.info('Creating an instance of ACL')

    def _getEntriesFromData(self):
        if not self._data:
            return
        result = {}
        for entry in self._data['aces']:
            principalId = entry['principal']['principalId']
            direct = entry['isDirect']
            perms = entry['permissions']
            # create an ACE
            if len(perms) > 0:
                ace = BrowserACE(principalId, perms, direct)
                # append it to the dictionary
                result[principalId] = ace
        return result
            
    def addEntry(self, ace):

        """
        Adds an :class:`ACE` entry to the ACL.

        >>> acl = folder.getACL()
        >>> acl.addEntry(ACE('jpotts', 'cmis:read', 'true'))
        >>> acl.addEntry(ACE('jsmith', 'cmis:write', 'true'))
        >>> acl.getEntries()
        {u'GROUP_EVERYONE': <cmislib.model.ACE object at 0x100731410>, u'jdoe': <cmislib.model.ACE object at 0x100731150>, 'jpotts': <cmislib.model.ACE object at 0x1005a22d0>, 'jsmith': <cmislib.model.ACE object at 0x1005a2210>}
        """

        pass

    def removeEntry(self, principalId):

        """
        Removes the :class:`ACE` entry given a specific principalId.

        >>> acl.getEntries()
        {u'GROUP_EVERYONE': <cmislib.model.ACE object at 0x100731410>, u'jdoe': <cmislib.model.ACE object at 0x100731150>, 'jpotts': <cmislib.model.ACE object at 0x1005a22d0>, 'jsmith': <cmislib.model.ACE object at 0x1005a2210>}
        >>> acl.removeEntry('jsmith')
        >>> acl.getEntries()
        {u'GROUP_EVERYONE': <cmislib.model.ACE object at 0x100731410>, u'jdoe': <cmislib.model.ACE object at 0x100731150>, 'jpotts': <cmislib.model.ACE object at 0x1005a22d0>}
        """

        pass

    def clearEntries(self):

        """
        Clears all :class:`ACE` entries from the ACL and removes the internal
        XML representation of the ACL.

        >>> acl = ACL()
        >>> acl.addEntry(ACE('jsmith', 'cmis:write', 'true'))
        >>> acl.addEntry(ACE('jpotts', 'cmis:write', 'true'))
        >>> acl.entries
        {'jpotts': <cmislib.model.ACE object at 0x1012c7310>, 'jsmith': <cmislib.model.ACE object at 0x100528490>}
        >>> acl.getXmlDoc()
        <xml.dom.minidom.Document instance at 0x1012cbb90>
        >>> acl.clearEntries()
        >>> acl.entries
        >>> acl.getXmlDoc()
        """

        pass

    def getEntries(self):

        """
        Returns a dictionary of :class:`ACE` objects for each Access Control
        Entry in the ACL. The key value is the ACE principalid.

        >>> acl = ACL()
        >>> acl.addEntry(ACE('jsmith', 'cmis:write', 'true'))
        >>> acl.addEntry(ACE('jpotts', 'cmis:write', 'true'))
        >>> for ace in acl.entries.values():
        ...     print 'principal:%s has the following permissions...' % ace.principalId
        ...     for perm in ace.permissions:
        ...             print perm
        ...
        principal:jpotts has the following permissions...
        cmis:write
        principal:jsmith has the following permissions...
        cmis:write
        """

        if self._entries:
            return self._entries
        else:
            if self._data:
                # parse data and build entry list
                self._entries = self._getEntriesFromData()
                # then return it
                return self._entries

    entries = property(getEntries)


class BrowserACE(ACE):

    pass


class BrowserChangeEntry(object):

    """
    Represents a change log entry. Retrieve a list of change entries via
    :meth:`Repository.getContentChanges`.

    >>> for changeEntry in rs:
    ...     changeEntry.objectId
    ...     changeEntry.id
    ...     changeEntry.changeType
    ...     changeEntry.changeTime
    ...
    'workspace://SpacesStore/0e2dc775-16b7-4634-9e54-2417a196829b'
    u'urn:uuid:0e2dc775-16b7-4634-9e54-2417a196829b'
    u'created'
    datetime.datetime(2010, 2, 11, 12, 55, 14)
    'workspace://SpacesStore/bd768f9f-99a7-4033-828d-5b13f96c6923'
    u'urn:uuid:bd768f9f-99a7-4033-828d-5b13f96c6923'
    u'updated'
    datetime.datetime(2010, 2, 11, 12, 55, 13)
    'workspace://SpacesStore/572c2cac-6b26-4cd8-91ad-b2931fe5b3fb'
    u'urn:uuid:572c2cac-6b26-4cd8-91ad-b2931fe5b3fb'
    u'updated'
    """

    def getId(self):
        """
        Returns the unique ID of the change entry.
        """
        #TODO need to implement
        pass

    def getObjectId(self):
        """
        Returns the object ID of the object that changed.
        """
        #TODO need to implement
        pass

    def getChangeType(self):

        """
        Returns the type of change that occurred. The resulting value must be
        one of:

         - created
         - updated
         - deleted
         - security
        """
        #TODO need to implement
        pass

    def getACL(self):

        """
        Gets the :class:`ACL` object that is included with this Change Entry.
        """
        #TODO need to implement
        pass

    def getChangeTime(self):

        """
        Returns a datetime object representing the time the change occurred.
        """
        #TODO need to implement
        pass

    def getProperties(self):

        """
        Returns the properties of the change entry. Note that depending on the
        capabilities of the repository ("capabilityChanges") the list may not
        include the actual property values that changed.
        """
        #TODO need to implement
        pass

    id = property(getId)
    objectId = property(getObjectId)
    changeTime = property(getChangeTime)
    changeType = property(getChangeType)
    properties = property(getProperties)


class BrowserChangeEntryResultSet(ResultSet):

    """
    A specialized type of :class:`ResultSet` that knows how to instantiate
    :class:`ChangeEntry` objects. The parent class assumes children of
    :class:`CmisObject` which doesn't work for ChangeEntries.
    """

    def __iter__(self):

        """
        Overriding to make it work with a list instead of a dict.
        """

        return iter(self.getResults())

    def __getitem__(self, index):

        """
        Overriding to make it work with a list instead of a dict.
        """

        return self.getResults()[index]

    def __len__(self):

        """
        Overriding to make it work with a list instead of a dict.
        """

        return len(self.getResults())

    def getResults(self):

        """
        Overriding to make it work with a list instead of a dict.
        """
        #TODO need to implement
        pass


class BrowserRendition(object):

    """
    This class represents a Rendition.
    """

    def __init__(self, propNode):
        """Constructor"""
        self.xmlDoc = propNode
        self.logger = logging.getLogger('cmislib.browser_binding.BrowserRendition')
        self.logger.info('Creating an instance of Rendition')

    def __str__(self):
        """To string"""
        return self.getStreamId()

    def getStreamId(self):
        """Getter for the rendition's stream ID"""
        #TODO need to implement
        pass

    def getMimeType(self):
        """Getter for the rendition's mime type"""
        #TODO need to implement
        pass

    def getLength(self):
        """Getter for the renditions's length"""
        #TODO need to implement
        pass

    def getTitle(self):
        """Getter for the renditions's title"""
        #TODO need to implement
        pass

    def getKind(self):
        """Getter for the renditions's kind"""
        #TODO need to implement
        pass

    def getHeight(self):
        """Getter for the renditions's height"""
        #TODO need to implement
        pass

    def getWidth(self):
        """Getter for the renditions's width"""
        #TODO need to implement
        pass

    def getHref(self):
        """Getter for the renditions's href"""
        #TODO need to implement
        pass

    def getRenditionDocumentId(self):
        """Getter for the renditions's width"""
        #TODO need to implement
        pass

    streamId = property(getStreamId)
    mimeType = property(getMimeType)
    length = property(getLength)
    title = property(getTitle)
    kind = property(getKind)
    height = property(getHeight)
    width = property(getWidth)
    href = property(getHref)
    renditionDocumentId = property(getRenditionDocumentId)


class BrowserCmisId(str):

    """
    This is a marker class to be used for Strings that are used as CMIS ID's.
    Making the objects instances of this class makes it easier to create the
    Atom entry XML with the appropriate type, ie, cmis:propertyId, instead of
    cmis:propertyString.
    """

    pass

def getSpecializedObject(obj, **kwargs):

    """
    Returns an instance of the appropriate :class:`CmisObject` class or one
    of its child types depending on the specified baseType.
    """

    moduleLogger.debug('Inside getSpecializedObject')

    if 'cmis:baseTypeId' in obj.getProperties():
        baseType = obj.getProperties()['cmis:baseTypeId']
        if baseType == 'cmis:folder':
            return BrowserFolder(obj._cmisClient, obj._repository, obj.getObjectId(), obj.data, **kwargs)
        if baseType == 'cmis:document':
            return BrowserDocument(obj._cmisClient, obj._repository, obj.getObjectId(), obj.data, **kwargs)
        if baseType == 'cmis:relationship':
            return BrowserRelationship(obj._cmisClient, obj._repository, obj.getObjectId(), obj.data, **kwargs)
        if baseType == 'cmis:policy':
            return BrowserPolicy(obj._cmisClient, obj._repository, obj.getObjectId(), obj.data, **kwargs)

    # if the base type ID wasn't found in the props (this can happen when
    # someone runs a query that doesn't select * or doesn't individually
    # specify baseTypeId) or if the type isn't one of the known base
    # types, give the object back
    return obj
