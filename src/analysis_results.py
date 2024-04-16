from typing import Dict, Any, List, Optional
import base64


class GenericObject:
    """Base class for result objects"""

    def __init__(self) -> None:
        self.children: List[GenericObject] = []

    def to_dict(self) -> Dict[str, Any]:
        """Serialize object to json-dumpable dict
        :return: dictionary with all of objects data
        """
        return {"object": "object"}

    def to_dict_recursive(self) -> Dict[str, Any]:
        """Serialize object and all of its children recursively to json-dumpable dict
        :return: dictionary with all of objects and its childrens data
        """
        self_dict = self.to_dict()
        self_dict["children"] = [child.to_dict_recursive() for child in self.children]
        return self_dict

    def push_config(
        self,
        config: Dict[str, Any],
        config_type: str,
        tags: Optional[List[str]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        comments: Optional[List[str]] = None,
    ) -> "Config":
        """Add a result config
        :param config: config data
        :param config_type: config type, probably `dynamic` or `static`
        :param tags: config tags to be added on mwdb, defaults to None
        :param attributes: attributes to be added on mwdb, defaults to None
        :param comments: comments to be added on mwdb, defaults to None
        :return: appended config object
        """
        cfg = Config(
            config=config,
            config_type=config_type,
            tags=tags,
            attributes=attributes,
            comments=comments,
        )
        self.children.append(cfg)
        return cfg

    def push_binary(
        self,
        data: bytes,
        name: str,
        tags: Optional[List[str]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        comments: Optional[List[str]] = None,
    ) -> "Binary":
        """Add a result binary
        :param data: binary data
        :param name: binary filename
        :param tags: binary tags to be added on mwdb, defaults to None
        :param attributes: attributes to be added on mwdb, defaults to None
        :param comments: comments to be added on mwdb, defaults to None
        :return: appended binary object
        """
        binary = Binary(
            data=data, name=name, tags=tags, attributes=attributes, comments=comments
        )
        self.children.append(binary)
        return binary

    def push_blob(
        self,
        content: str,
        name: str,
        blob_type: str,
        tags: Optional[List[str]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        comments: Optional[List[str]] = None,
    ) -> "Blob":
        """Add a result blob
        :param content: blob data
        :param name: blob filename
        :param blob_type: blob type, usually `dyn_cfg`
        :param tags: blob tags to be added on mwdb, defaults to None
        :param attributes: attributes to be added on mwdb, defaults to None
        :param comments: comments to be added on mwdb, defaults to None
        :return: appended config blob
        """
        blob = Blob(
            content=content,
            name=name,
            blob_type=blob_type,
            tags=tags,
            attributes=attributes,
            comments=comments,
        )
        self.children.append(blob)
        return blob


class Config(GenericObject):
    def __init__(
        self,
        config: Dict[str, Any],
        config_type: str,
        tags: Optional[List[str]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        comments: Optional[List[str]] = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.config_type = config_type
        self.tags = tags or []
        self.attributes = attributes or {}
        self.comments = comments or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "object": "config",
            "config": self.config,
            "config_type": self.config_type,
            "tags": self.tags,
            "attributes": self.attributes,
            "comments": self.comments,
        }


class Binary(GenericObject):
    def __init__(
        self,
        data: bytes,
        name: str,
        tags: Optional[List[str]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        comments: Optional[List[str]] = None,
    ) -> None:
        super().__init__()
        self.data = data
        self.name = name
        self.tags = tags or []
        self.attributes = attributes or {}
        self.comments = comments or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "object": "binary",
            "data": base64.b64encode(self.data).decode("utf-8"),
            "name": self.name,
            "tags": self.tags,
            "attributes": self.attributes,
            "comments": self.comments,
        }


class Blob(GenericObject):
    def __init__(
        self,
        content: str,
        name: str,
        blob_type: str,
        tags: Optional[List[str]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        comments: Optional[List[str]] = None,
    ) -> None:
        super().__init__()
        self.content = content
        self.name = name
        self.blob_type = blob_type
        self.tags = tags or []
        self.attributes = attributes or {}
        self.comments = comments or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "object": "blob",
            "content": self.content,
            "blob_type": self.blob_type,
            "name": self.name,
            "tags": self.tags,
            "attributes": self.attributes,
            "comments": self.comments,
        }
