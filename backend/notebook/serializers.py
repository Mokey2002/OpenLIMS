from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import (
    Experiment,
    ExperimentBlock,
    ExperimentComment,
    ExperimentLink,
    ExperimentRevision,
    ExperimentReview,
    ExperimentTemplate,
    Notebook,
)
from .permissions import user_can_notebook


User = get_user_model()
NOTEBOOK_PERMISSION_ACTIONS = ("read", "write", "comment", "review", "lock")


def notebook_permissions_for_serializer(context, notebook):
    if context.get("all_notebook_permissions"):
        return {action: True for action in NOTEBOOK_PERMISSION_ACTIONS}

    request = context.get("request")
    if request and notebook.owner_id == request.user.pk:
        return {action: True for action in NOTEBOOK_PERMISSION_ACTIONS}

    permission_ids = context.get("notebook_permission_ids")
    if permission_ids is not None:
        return {
            action: notebook.pk in permission_ids.get(action, set())
            for action in NOTEBOOK_PERMISSION_ACTIONS
        }

    user = context["request"].user
    return {
        action: user_can_notebook(user, notebook, action)
        for action in NOTEBOOK_PERMISSION_ACTIONS
    }


class NotebookCollaboratorSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "full_name"]
        read_only_fields = fields


class NotebookSerializer(serializers.ModelSerializer):
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    project_code = serializers.CharField(source="project.code", read_only=True)
    experiment_count = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = Notebook
        fields = [
            "id", "public_id", "name", "description", "scope", "owner",
            "owner_username", "project", "project_code", "team_members", "readers",
            "editors", "commenters", "reviewers", "lockers", "experiment_count",
            "permissions", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "public_id", "owner", "owner_username", "experiment_count", "permissions", "created_at", "updated_at"]

    def get_experiment_count(self, obj):
        annotated_count = getattr(obj, "experiment_count", None)
        return annotated_count if annotated_count is not None else obj.experiments.count()

    def get_permissions(self, obj):
        return notebook_permissions_for_serializer(self.context, obj)

    def validate(self, attrs):
        scope = attrs.get("scope", getattr(self.instance, "scope", Notebook.SCOPE_USER))
        project = attrs.get("project", getattr(self.instance, "project", None))
        if scope == Notebook.SCOPE_PROJECT and not project:
            raise serializers.ValidationError({"project": "Project-scoped notebooks require a project."})
        if scope != Notebook.SCOPE_PROJECT and project:
            raise serializers.ValidationError({"project": "Only project-scoped notebooks may select a project."})
        return attrs


class ExperimentTemplateSerializer(serializers.ModelSerializer):
    notebook_name = serializers.CharField(source="notebook.name", read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = ExperimentTemplate
        fields = [
            "id", "public_id", "notebook", "notebook_name", "name", "description",
            "blocks", "active", "created_by", "created_by_username", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "public_id", "created_by", "created_by_username", "created_at", "updated_at"]

    def validate_blocks(self, value):
        from .services import validate_blocks

        return [
            {"block_type": block["block_type"], "data": block["data"]}
            for block in validate_blocks(value)
        ]

    def validate_notebook(self, value):
        if self.instance and value.pk != self.instance.notebook_id:
            raise serializers.ValidationError("Templates cannot be moved between notebooks; create a new template instead.")
        return value


class ExperimentBlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExperimentBlock
        fields = ["id", "public_id", "position", "block_type", "data"]


class ExperimentLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExperimentLink
        fields = [
            "id", "public_id", "entity_type", "entity_public_id", "relation_type",
            "label", "version", "created_at",
        ]


class ExperimentReviewSerializer(serializers.ModelSerializer):
    reviewer_username = serializers.CharField(source="reviewer.username", read_only=True)
    revision_number = serializers.IntegerField(source="revision.number", read_only=True)

    class Meta:
        model = ExperimentReview
        fields = [
            "id", "public_id", "revision", "revision_number", "reviewer",
            "reviewer_username", "decision", "comment", "signed_name",
            "content_checksum", "reviewed_at",
        ]
        read_only_fields = fields


class ExperimentRevisionSummarySerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    restored_from_number = serializers.IntegerField(source="restored_from.number", read_only=True)

    class Meta:
        model = ExperimentRevision
        fields = [
            "id", "public_id", "number", "checksum", "change_summary",
            "parent_revision", "restored_from", "restored_from_number", "created_by",
            "created_by_username", "created_at",
        ]
        read_only_fields = fields


class ExperimentRevisionSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    restored_from_number = serializers.IntegerField(source="restored_from.number", read_only=True)
    blocks = ExperimentBlockSerializer(many=True, read_only=True)
    links = ExperimentLinkSerializer(many=True, read_only=True)
    reviews = ExperimentReviewSerializer(many=True, read_only=True)

    class Meta:
        model = ExperimentRevision
        fields = [
            "id", "public_id", "number", "checksum", "change_summary",
            "parent_revision", "restored_from", "restored_from_number", "created_by",
            "created_by_username", "created_at", "blocks", "links", "reviews",
        ]
        read_only_fields = fields


class ExperimentCommentSerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source="author.username", read_only=True)
    assigned_to_username = serializers.CharField(source="assigned_to.username", read_only=True)
    mention_usernames = serializers.SerializerMethodField()

    class Meta:
        model = ExperimentComment
        fields = [
            "id", "public_id", "experiment", "revision", "author", "author_username",
            "body", "mentions", "mention_usernames", "assigned_to", "assigned_to_username",
            "resolved", "resolved_by", "resolved_at", "created_at",
        ]
        read_only_fields = [
            "id", "public_id", "author", "author_username", "mention_usernames",
            "resolved_by", "resolved_at", "created_at",
        ]

    def get_mention_usernames(self, obj):
        return [user.username for user in obj.mentions.all()]

    def validate(self, attrs):
        experiment = attrs.get("experiment", getattr(self.instance, "experiment", None))
        revision = attrs.get("revision", getattr(self.instance, "revision", None))
        if revision and experiment and revision.experiment_id != experiment.pk:
            raise serializers.ValidationError({"revision": "The revision does not belong to this experiment."})
        return attrs


class ExperimentSerializer(serializers.ModelSerializer):
    notebook_name = serializers.CharField(source="notebook.name", read_only=True)
    project = serializers.IntegerField(source="notebook.project_id", read_only=True)
    project_code = serializers.CharField(source="notebook.project.code", read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    locked_by_username = serializers.CharField(source="locked_by.username", read_only=True)
    current_revision_detail = ExperimentRevisionSerializer(source="current_revision", read_only=True)
    revisions = ExperimentRevisionSerializer(many=True, read_only=True)
    comments = ExperimentCommentSerializer(many=True, read_only=True)
    reviews = ExperimentReviewSerializer(many=True, read_only=True)
    permissions = serializers.SerializerMethodField()
    assignee_usernames = serializers.SerializerMethodField()
    initial_blocks = serializers.ListField(child=serializers.DictField(), write_only=True, required=False)
    initial_links = serializers.ListField(child=serializers.DictField(), write_only=True, required=False)

    class Meta:
        model = Experiment
        fields = [
            "id", "public_id", "notebook", "notebook_name", "project", "project_code",
            "template", "cloned_from", "title", "status", "created_by",
            "created_by_username", "assignees", "assignee_usernames", "current_revision",
            "current_revision_detail", "revisions", "comments", "reviews", "permissions",
            "completed_at", "reviewed_at", "locked_at", "locked_by", "locked_by_username",
            "created_at", "updated_at", "initial_blocks", "initial_links",
        ]
        read_only_fields = [
            "id", "public_id", "cloned_from", "status", "created_by", "created_by_username",
            "current_revision", "current_revision_detail", "revisions", "comments", "reviews",
            "permissions", "completed_at", "reviewed_at", "locked_at", "locked_by",
            "locked_by_username", "created_at", "updated_at",
        ]

    def get_permissions(self, obj):
        return notebook_permissions_for_serializer(self.context, obj.notebook)

    def get_assignee_usernames(self, obj):
        return [user.username for user in obj.assignees.all()]

    def validate(self, attrs):
        notebook = attrs.get("notebook", getattr(self.instance, "notebook", None))
        template = attrs.get("template", getattr(self.instance, "template", None))
        if template and notebook and template.notebook_id != notebook.pk:
            raise serializers.ValidationError({"template": "The template belongs to a different notebook."})
        if self.instance and notebook and notebook.pk != self.instance.notebook_id:
            raise serializers.ValidationError({"notebook": "Experiments cannot be moved between notebooks; clone the experiment instead."})
        return attrs


class ExperimentCompactSerializer(ExperimentSerializer):
    revisions = ExperimentRevisionSummarySerializer(many=True, read_only=True)


class ExperimentSummarySerializer(serializers.ModelSerializer):
    notebook_name = serializers.CharField(source="notebook.name", read_only=True)
    project = serializers.IntegerField(source="notebook.project_id", read_only=True)
    project_code = serializers.CharField(source="notebook.project.code", read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    current_revision_detail = ExperimentRevisionSummarySerializer(source="current_revision", read_only=True)
    permissions = serializers.SerializerMethodField()
    assignee_usernames = serializers.SerializerMethodField()
    open_comment_count = serializers.SerializerMethodField()

    class Meta:
        model = Experiment
        fields = [
            "id", "public_id", "notebook", "notebook_name", "project", "project_code",
            "template", "cloned_from", "title", "status", "created_by",
            "created_by_username", "assignees", "assignee_usernames", "current_revision",
            "current_revision_detail", "permissions", "open_comment_count", "completed_at",
            "reviewed_at", "locked_at", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_permissions(self, obj):
        return notebook_permissions_for_serializer(self.context, obj.notebook)

    def get_assignee_usernames(self, obj):
        return [user.username for user in obj.assignees.all()]

    def get_open_comment_count(self, obj):
        return getattr(obj, "open_comment_count", 0)
