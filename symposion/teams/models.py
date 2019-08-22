from __future__ import unicode_literals

import datetime

from django.db import models
from django.urls import reverse
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import ugettext_lazy as _

from django.contrib.auth.models import Permission
from django.contrib.auth import get_user_model

from reversion import revisions as reversion

User = get_user_model()


TEAM_ACCESS_CHOICES = [
    ("open", _("open")),
    ("application", _("by application")),
    ("invitation", _("by invitation"))
]


@python_2_unicode_compatible
class Team(models.Model):

    slug = models.SlugField(unique=True, verbose_name=_("Slug"))
    name = models.CharField(max_length=100, verbose_name=_("Name"))
    description = models.TextField(blank=True, verbose_name=_("Description"))
    access = models.CharField(max_length=20, choices=TEAM_ACCESS_CHOICES,
                              verbose_name=_("Access"))

    # member permissions
    permissions = models.ManyToManyField(Permission, blank=True,
                                         related_name="member_teams",
                                         verbose_name=_("Permissions"))

    # manager permissions
    manager_permissions = models.ManyToManyField(Permission, blank=True,
                                                 related_name="manager_teams",
                                                 verbose_name=_("Manager permissions"))

    created = models.DateTimeField(default=datetime.datetime.now,
                                   editable=False, verbose_name=_("Created"))

    def get_absolute_url(self):
        return reverse("team_detail", [self.slug])

    def __str__(self):
        return self.name

    def get_state_for_user(self, user):
        try:
            return self.memberships.get(user=user).state
        except Membership.DoesNotExist:
            return None

    def applicants(self):
        return self.memberships.filter(state="applied")

    def invitees(self):
        return self.memberships.filter(state="invited")

    def members(self):
        return self.memberships.filter(state="member")

    def managers(self):
        return self.memberships.filter(state="manager")

    class Meta:
        verbose_name = _('Team')
        verbose_name_plural = _('Teams')

MEMBERSHIP_STATE_CHOICES = [
    ("applied", _("applied")),
    ("invited", _("invited")),
    ("declined", _("declined")),
    ("rejected", _("rejected")),
    ("member", _("member")),
    ("manager", _("manager")),
]


class Membership(models.Model):

    user = models.ForeignKey(User, related_name="memberships",
                             verbose_name=_("User"), on_delete=models.CASCADE)
    team = models.ForeignKey(Team, related_name="memberships",
                             verbose_name=_("Team"), on_delete=models.CASCADE)
    state = models.CharField(max_length=20, choices=MEMBERSHIP_STATE_CHOICES,
                             verbose_name=_("State"))
    message = models.TextField(blank=True, verbose_name=_("Message"))

    class Meta:
        verbose_name = _("Membership")
        verbose_name_plural = _("Memberships")

reversion.register(Membership)
