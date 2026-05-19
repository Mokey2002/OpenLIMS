from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Project(models.Model):
    name = models.CharField(max_length=128, unique=True)
    code = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True)
    members = models.ManyToManyField(
        User,
        blank=True,
        related_name="projects",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

class ProjectPost(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="project_posts",
    )
    note = models.TextField(blank=True)
    image = models.ImageField(upload_to="project_posts/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.project.code} post by {self.author}"
