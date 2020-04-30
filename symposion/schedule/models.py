from __future__ import unicode_literals

import datetime

from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import ugettext_lazy as _

from django.contrib.auth import get_user_model

from symposion.markdown_parser import parse
from symposion.proposals.models import ProposalBase
from symposion.conference.models import Section
from symposion.speakers.models import SpeakerBase as Speaker

User = get_user_model()


@python_2_unicode_compatible
class Schedule(models.Model):

    section = models.OneToOneField(Section, verbose_name=_("Section"), on_delete=models.CASCADE)
    published = models.BooleanField(default=True, verbose_name=_("Published"))
    hidden = models.BooleanField(_("Hide schedule from overall conference view"), default=False)

    def __str__(self):
        return "%s Schedule" % self.section

    class Meta:
        ordering = ["section"]
        verbose_name = _('Schedule')
        verbose_name_plural = _('Schedules')


@python_2_unicode_compatible
class Day(models.Model):

    schedule = models.ForeignKey(Schedule, verbose_name=_("Schedule"), on_delete=models.CASCADE)
    date = models.DateField(verbose_name=_("Date"))

    def __str__(self):
        return "%s - %s" % (self.schedule.section.slug, self.date)

    class Meta:
        unique_together = [("schedule", "date")]
        ordering = ["date"]
        verbose_name = _("date")
        verbose_name_plural = _("dates")


@python_2_unicode_compatible
class Room(models.Model):

    schedule = models.ForeignKey(Schedule, verbose_name=_("Schedule"), on_delete=models.CASCADE)
    name = models.CharField(max_length=65, verbose_name=_("Name"))
    order = models.PositiveIntegerField(verbose_name=_("Order"))

    def __str__(self):
        return "%s - %s" % (self.schedule.section.slug, self.name)

    class Meta:
        verbose_name = _("Room")
        verbose_name_plural = _("Rooms")


@python_2_unicode_compatible
class SlotKind(models.Model):
    """
    A slot kind represents what kind a slot is. For example, a slot can be a
    break, lunch, or X-minute talk.
    """

    schedule = models.ForeignKey(Schedule, verbose_name=_("schedule"), on_delete=models.CASCADE)
    label = models.CharField(max_length=50, verbose_name=_("Label"))

    def __str__(self):
        return "%s - %s" % (self.schedule.section.slug, self.label)

    class Meta:
        verbose_name = _("Slot kind")
        verbose_name_plural = _("Slot kinds")


@python_2_unicode_compatible
class Slot(models.Model):

    name = models.CharField(max_length=256, editable=False)
    day = models.ForeignKey(Day, verbose_name=_("Day"), on_delete=models.CASCADE)
    kind = models.ForeignKey(SlotKind, verbose_name=_("Kind"), on_delete=models.CASCADE)
    start = models.TimeField(verbose_name=_("Start"))
    end = models.TimeField(verbose_name=_("End"))
    content_override = models.TextField(blank=True, verbose_name=_("Content override"))
    content_override_html = models.TextField(blank=True)

    def assign(self, content):
        """
        Assign the given content to this slot and if a previous slot content
        was given we need to unlink it to avoid integrity errors.
        """
        self.unassign()
        content.slot = self
        content.save()

    def unassign(self):
        """
        Unassign the associated content with this slot.
        """
        content = self.content
        if content and content.slot_id:
            content.slot = None
            content.save()

    @property
    def content(self):
        """
        Return the content this slot represents.
        @@@ hard-coded for presentation for now
        """
        try:
            return self.content_ptr
        except ObjectDoesNotExist:
            return None

    @property
    def start_datetime(self):
        return datetime.datetime(
            self.day.date.year,
            self.day.date.month,
            self.day.date.day,
            self.start.hour,
            self.start.minute)

    @property
    def end_datetime(self):
        return datetime.datetime(
            self.day.date.year,
            self.day.date.month,
            self.day.date.day,
            self.end.hour,
            self.end.minute)

    @property
    def length_in_minutes(self):
        return int(
            (self.end_datetime - self.start_datetime).total_seconds() / 60)

    @property
    def rooms(self):
        return Room.objects.filter(pk__in=self.slotroom_set.values("room"))

    def save(self, *args, **kwargs):
        roomlist = ' '.join(map(lambda r: r.__str__(), self.rooms))
        self.name = "%s %s (%s - %s) %s" % (self.day, self.kind, self.start, self.end, roomlist)
        self.content_override_html = parse(self.content_override)
        super(Slot, self).save(*args, **kwargs)

    def __str__(self):
        return "%s - %s" % (self.day.schedule.section.slug, self.name)

    class Meta:
        ordering = ["day", "start", "end"]
        verbose_name = _("slot")
        verbose_name_plural = _("slots")


@python_2_unicode_compatible
class SlotRoom(models.Model):
    """
    Links a slot with a room.
    """

    slot = models.ForeignKey(Slot, verbose_name=_("Slot"), on_delete=models.CASCADE)
    room = models.ForeignKey(Room, verbose_name=_("Room"), on_delete=models.CASCADE)

    def __str__(self):
        return "%s - %s %s" % (self.room.schedule.section.slug, self.room, self.slot)

    class Meta:
        unique_together = [("slot", "room")]
        ordering = ["slot", "room__order"]
        verbose_name = _("Slot room")
        verbose_name_plural = _("Slot rooms")


@python_2_unicode_compatible
class Presentation(models.Model):

    slot = models.OneToOneField(Slot, null=True, blank=True, related_name="content_ptr", verbose_name=_("Slot"), on_delete=models.CASCADE)
    title = models.CharField(max_length=100, verbose_name=_("Title"))
    description = models.TextField(verbose_name=_("Description"))
    description_html = models.TextField(blank=True)
    abstract = models.TextField(blank=True, verbose_name=_("Abstract"))
    abstract_html = models.TextField(blank=True)
    speaker = models.ForeignKey(Speaker, related_name="presentations", verbose_name=_("Speaker"), on_delete=models.CASCADE)
    additional_speakers = models.ManyToManyField(Speaker, related_name="copresentations",
                                                 blank=True, verbose_name=_("Additional speakers"))
    cancelled = models.BooleanField(default=False, verbose_name=_("Cancelled"))
    proposal_base = models.OneToOneField(ProposalBase, related_name="presentation", verbose_name=_("Proposal base"), on_delete=models.CASCADE)
    section = models.ForeignKey(Section, related_name="presentations", verbose_name=_("Section"), on_delete=models.CASCADE)
    youtube_link = models.CharField(max_length=128, null=True, blank=True)

    def save(self, *args, **kwargs):
        self.description_html = parse(self.description)
        self.abstract_html = parse(self.abstract)
        return super(Presentation, self).save(*args, **kwargs)

    @property
    def number(self):
        return self.proposal.number

    @property
    def proposal(self):
        if self.proposal_base_id is None:
            return None
        return ProposalBase.objects.get_subclass(pk=self.proposal_base_id)

    def speakers(self):
        yield self.speaker
        for speaker in self.additional_speakers.all():
            yield speaker

    def __str__(self):
        return "#%s %s (%s)" % (self.number, self.title, self.speaker)

    class Meta:
        ordering = ["slot"]
        verbose_name = _("presentation")
        verbose_name_plural = _("presentations")


@python_2_unicode_compatible
class Session(models.Model):

    day = models.ForeignKey(Day, related_name="sessions", verbose_name=_("Day"), on_delete=models.CASCADE)
    slots = models.ManyToManyField(Slot, related_name="sessions", verbose_name=_("Slots"))

    def sorted_slots(self):
        return self.slots.order_by("start")

    def start(self):
        slots = self.sorted_slots()
        if slots:
            return list(slots)[0].start
        else:
            return None

    def end(self):
        slots = self.sorted_slots()
        if slots:
            return list(slots)[-1].end
        else:
            return None

    def __str__(self):
        start = self.start()
        end = self.end()
        if start and end:
            return "%s: %s - %s" % (
                self.day.date.strftime("%a"),
                start.strftime("%X"),
                end.strftime("%X")
            )
        return ""

    @property
    def needs_volunteers(self):
        chair = SessionRole.objects.filter(session=self, role=SessionRole.SESSION_ROLE_CHAIR).exclude(status=False)
        runner = SessionRole.objects.filter(session=self, role=SessionRole.SESSION_ROLE_RUNNER).exclude(status=False)
        return not (chair and runner)

    class Meta:
        verbose_name = _("Session")
        verbose_name_plural = _("Sessions")


@python_2_unicode_compatible
class SessionRole(models.Model):

    SESSION_ROLE_CHAIR = 1
    SESSION_ROLE_RUNNER = 2

    SESSION_ROLE_TYPES = [
        (SESSION_ROLE_CHAIR, _("Session Chair")),
        (SESSION_ROLE_RUNNER, _("Session Runner")),
    ]

    session = models.ForeignKey(Session, verbose_name=_("Session"), on_delete=models.CASCADE)
    user = models.ForeignKey(User, verbose_name=_("User"), on_delete=models.CASCADE)
    role = models.IntegerField(choices=SESSION_ROLE_TYPES, verbose_name=_("Role"))
    status = models.NullBooleanField(verbose_name=_("Status"))

    submitted = models.DateTimeField(default=datetime.datetime.now)

    class Meta:
        unique_together = [("session", "user", "role")]
        verbose_name = _("Session role")
        verbose_name_plural = _("Session roles")

    def __str__(self):
        return "%s %s: %s" % (self.user, self.session,
                              self.SESSION_ROLE_TYPES[self.role - 1][1])
