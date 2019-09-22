# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from datetime import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError

from django.db import models
from django.db.models import Q, F
from django.db.models import Case, When, Value
from django.db.models import Count
from django.db.models.signals import post_save

from django.utils.translation import ugettext_lazy as _

from django.contrib.auth import get_user_model

from symposion.markdown_parser import parse
from symposion.proposals.models import ProposalBase
from symposion.schedule.models import Presentation
from symposion.utils import anonymous_review


User = get_user_model()

# How we compute proposal scores: 3*(+1's) + (+0's) - (-0's) - 3*(-1's)
PROPOSAL_SCORE_EXPRESSION = \
    3 * F('plus_one') + F('plus_zero') - F('minus_zero') - 3 * F('minus_one')

class Votes(object):
    """
    *** NOTE ***

    The MINUS_ZERO and MINUS_ONE values here are using fancy Unicode
    minus signs instead of ASCII minus sign/dashes.  This works fine so
    long as everything using these does it consistently; just be careful
    to use VOTES.MINUS_ZERO instead of writing out "-0" anywhere.
    """
    PLUS_ONE = "+1"
    PLUS_ZERO = "+0"
    MINUS_ZERO = u"−0"
    MINUS_ONE = u"−1"

    CHOICES = [
        (PLUS_ONE, u"+1 — Good proposal and I will argue for it to be accepted."),
        (PLUS_ZERO, u"+0 — OK proposal, but I will not argue for it to be accepted."),
        (MINUS_ZERO, u"−0 — Weak proposal, but I will not argue strongly against acceptance."),
        (MINUS_ONE, u"−1 — Serious issues and I will argue to reject this proposal."),
    ]
VOTES = Votes()



class ReviewAssignment(models.Model):
    AUTO_ASSIGNED_INITIAL = 0
    OPT_IN = 1
    AUTO_ASSIGNED_LATER = 2

    NUM_REVIEWERS = 3

    ORIGIN_CHOICES = [
        (AUTO_ASSIGNED_INITIAL, _("auto-assigned, initial")),
        (OPT_IN, _("opted-in")),
        (AUTO_ASSIGNED_LATER, _("auto-assigned, later")),
    ]

    proposal = models.ForeignKey(ProposalBase, verbose_name=_("Proposal"), on_delete=models.CASCADE)
    user = models.ForeignKey(User, verbose_name=_("User"), on_delete=models.CASCADE)

    origin = models.IntegerField(choices=ORIGIN_CHOICES, verbose_name=_("Origin"))

    assigned_at = models.DateTimeField(default=datetime.now, verbose_name=_("Assigned at"))
    opted_out = models.BooleanField(default=False, verbose_name=_("Opted out"))

    @classmethod
    def create_assignments(cls, proposal, origin=AUTO_ASSIGNED_INITIAL):
        speakers = [proposal.speaker] + list(proposal.additional_speakers.all())
        reviewers = User.objects.exclude(
            pk__in=[
                speaker.user_id
                for speaker in speakers
                if speaker.user_id is not None
            ] + [
                assignment.user_id
                for assignment in ReviewAssignment.objects.filter(
                    proposal_id=proposal.id)]
        ).filter(
            groups__name="reviewers",
        ).filter(
            Q(reviewassignment__opted_out=False) | Q(reviewassignment=None)
        ).annotate(
            num_assignments=models.Count("reviewassignment")
        ).order_by(
            "num_assignments", "?",
        )
        num_assigned_reviewers = ReviewAssignment.objects.filter(
            proposal_id=proposal.id, opted_out=0).count()
        for reviewer in reviewers[:max(0, cls.NUM_REVIEWERS - num_assigned_reviewers)]:
            cls._default_manager.create(
                proposal=proposal,
                user=reviewer,
                origin=origin,
            )


class ProposalMessage(models.Model):
    proposal = models.ForeignKey(ProposalBase, related_name="messages", verbose_name=_("Proposal"), on_delete=models.CASCADE)
    user = models.ForeignKey(User, verbose_name=_("User"), on_delete=models.CASCADE)

    message = models.TextField(verbose_name=_("Message"))
    message_html = models.TextField(blank=True)
    submitted_at = models.DateTimeField(default=datetime.now, editable=False, verbose_name=_("Submitted at"))

    def save(self, *args, **kwargs):
        self.message_html = parse(self.message)
        return super(ProposalMessage, self).save(*args, **kwargs)

    class Meta:
        ordering = ["submitted_at"]
        verbose_name = _("proposal message")
        verbose_name_plural = _("proposal messages")


    def redacted(self):
        ''' If this message's proposal has anonymous_review switched on, then
        return a read-only proxy that hides the user *if* the user is a
        proposer. Otherwise, return this proposal.
        '''

        if self.proposal.anonymous_review():
            return anonymous_review.MessageProxy(self)

        return self


class Review(models.Model):
    VOTES = VOTES

    proposal = models.ForeignKey(ProposalBase, related_name="reviews", verbose_name=_("Proposal"), on_delete=models.CASCADE)
    user = models.ForeignKey(User, verbose_name=_("User"), on_delete=models.CASCADE)

    # No way to encode "-0" vs. "+0" into an IntegerField, and I don't feel
    # like some complicated encoding system.
    vote = models.CharField(max_length=2, blank=True, choices=VOTES.CHOICES, verbose_name=_("Vote"))
    comment = models.TextField(
        blank=True,
        verbose_name=_("Comment")
    )
    comment_html = models.TextField(blank=True)
    submitted_at = models.DateTimeField(default=datetime.now, editable=False, verbose_name=_("Submitted at"))

    def save(self, **kwargs):
        self.comment_html = parse(self.comment)
        if self.vote:
            vote, created = LatestVote.objects.get_or_create(
                proposal=self.proposal,
                user=self.user,
                defaults=dict(
                    vote=self.vote,
                    submitted_at=self.submitted_at,
                )
            )
            if not created:
                LatestVote.objects.filter(pk=vote.pk).update(vote=self.vote)
                self.proposal.result.update_vote(self.vote, previous=vote.vote)
            else:
                self.proposal.result.update_vote(self.vote)
        super(Review, self).save(**kwargs)

    def delete(self):
        model = self.__class__
        user_reviews = model._default_manager.filter(
            proposal=self.proposal,
            user=self.user,
        )
        try:
            # find the latest review
            latest = user_reviews.exclude(pk=self.pk).order_by("-submitted_at")[0]
        except IndexError:
            # did not find a latest which means this must be the only one.
            # treat it as a last, but delete the latest vote.
            self.proposal.result.update_vote(self.vote, removal=True)
            lv = LatestVote.objects.filter(proposal=self.proposal, user=self.user)
            lv.delete()
        else:
            # handle that we've found a latest vote
            # check if self is the lastest vote
            if self == latest:
                # self is the latest review; revert the latest vote to the
                # previous vote
                previous = user_reviews.filter(submitted_at__lt=self.submitted_at)\
                    .order_by("-submitted_at")[0]
                self.proposal.result.update_vote(self.vote, previous=previous.vote, removal=True)
                lv = LatestVote.objects.filter(proposal=self.proposal, user=self.user)
                lv.update(
                    vote=previous.vote,
                    submitted_at=previous.submitted_at,
                )
            else:
                # self is not the latest review so we just need to decrement
                # the comment count
                self.proposal.result.comment_count = models.F("comment_count") - 1
                self.proposal.result.save()
        # in all cases we need to delete the review; let's do it!
        super(Review, self).delete()

    def css_class(self):
        return {
            self.VOTES.PLUS_ONE: "plus-one",
            self.VOTES.PLUS_ZERO: "plus-zero",
            self.VOTES.MINUS_ZERO: "minus-zero",
            self.VOTES.MINUS_ONE: "minus-one",
        }[self.vote]

    @property
    def section(self):
        return self.proposal.kind.section.slug

    class Meta:
        verbose_name = _("review")
        verbose_name_plural = _("reviews")


class LatestVote(models.Model):
    VOTES = VOTES

    proposal = models.ForeignKey(ProposalBase, related_name="votes", verbose_name=_("Proposal"), on_delete=models.CASCADE)
    user = models.ForeignKey(User, verbose_name=_("User"), on_delete=models.CASCADE)

    # No way to encode "-0" vs. "+0" into an IntegerField, and I don't feel
    # like some complicated encoding system.
    vote = models.CharField(max_length=2, choices=VOTES.CHOICES, verbose_name=_("Vote"))
    submitted_at = models.DateTimeField(default=datetime.now, editable=False, verbose_name=_("Submitted at"))

    class Meta:
        unique_together = [("proposal", "user")]
        verbose_name = _("latest vote")
        verbose_name_plural = _("latest votes")

    def css_class(self):
        return {
            self.VOTES.PLUS_ONE: "plus-one",
            self.VOTES.PLUS_ZERO: "plus-zero",
            self.VOTES.MINUS_ZERO: "minus-zero",
            self.VOTES.MINUS_ONE: "minus-one",
        }[self.vote]


class ProposalResult(models.Model):
    proposal = models.OneToOneField(ProposalBase, related_name="result", verbose_name=_("Proposal"), on_delete=models.CASCADE)
    score = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"), verbose_name=_("Score"))
    comment_count = models.PositiveIntegerField(default=0, verbose_name=_("Comment count"))
    vote_count = models.PositiveIntegerField(default=0, verbose_name=_("Vote count"))
    plus_one = models.PositiveIntegerField(default=0)
    plus_zero = models.PositiveIntegerField(default=0)
    minus_zero = models.PositiveIntegerField(default=0)
    minus_one = models.PositiveIntegerField(default=0)
    accepted = models.NullBooleanField(choices=[
        (True, "accepted"),
        (False, "rejected"),
        (None, "undecided"),
    ], default=None, verbose_name=_("Accepted"))
    status = models.CharField(max_length=20, choices=[
        ("accepted", _("accepted")),
        ("rejected", _("rejected")),
        ("undecided", _("undecided")),
        ("standby", _("standby")),
    ], default="undecided", verbose_name=_("Status"))

    @classmethod
    def full_calculate(cls):
        for proposal in ProposalBase.objects.all():
            result, created = cls._default_manager.get_or_create(proposal=proposal)
            result.update_vote()

    def update_vote(self, *a, **k):
        proposal = self.proposal
        self.comment_count = Review.objects.filter(proposal=proposal).count()
        agg = LatestVote.objects.filter(proposal=proposal).values(
            "vote"
        ).annotate(
            count=Count("vote")
        )
        vote_count = {}
        # Set the defaults
        for option in VOTES.CHOICES:
            vote_count[option[0]] = 0
        # Set the actual values if present
        for d in agg:
            vote_count[d["vote"]] = d["count"]

        self.plus_one = vote_count[VOTES.PLUS_ONE]
        self.plus_zero = vote_count[VOTES.PLUS_ZERO]
        self.minus_zero = vote_count[VOTES.MINUS_ZERO]
        self.minus_one = vote_count[VOTES.MINUS_ONE]
        self.vote_count = sum(i[1] for i in vote_count.items())
        self.save()
        model = self.__class__
        model._default_manager.filter(pk=self.pk).update(score=PROPOSAL_SCORE_EXPRESSION)

    class Meta:
        verbose_name = _("proposal_result")
        verbose_name_plural = _("proposal_results")


class Comment(models.Model):
    proposal = models.ForeignKey(ProposalBase, related_name="comments", verbose_name=_("Proposal"), on_delete=models.CASCADE)
    commenter = models.ForeignKey(User, verbose_name=_("Commenter"), on_delete=models.CASCADE)
    text = models.TextField(verbose_name=_("Text"))
    text_html = models.TextField(blank=True)

    # Or perhaps more accurately, can the user see this comment.
    public = models.BooleanField(choices=[(True, _("public")), (False, _("private"))], default=False, verbose_name=_("Public"))
    commented_at = models.DateTimeField(default=datetime.now, verbose_name=_("Commented at"))

    class Meta:
        verbose_name = _("comment")
        verbose_name_plural = _("comments")

    def save(self, *args, **kwargs):
        self.text_html = parse(self.text)
        return super(Comment, self).save(*args, **kwargs)


class NotificationTemplate(models.Model):

    label = models.CharField(max_length=256, verbose_name=_("Label"))
    from_address = models.EmailField(verbose_name=_("From address"))
    subject = models.CharField(max_length=256, verbose_name=_("Subject"))
    body = models.TextField(verbose_name=_("Body"))

    class Meta:
        verbose_name = _("notification template")
        verbose_name_plural = _("notification templates")


class ResultNotification(models.Model):

    proposal = models.ForeignKey(ProposalBase, related_name="notifications", verbose_name=_("Proposal"), on_delete=models.CASCADE)
    template = models.ForeignKey(NotificationTemplate, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("Template"))
    timestamp = models.DateTimeField(default=datetime.now, verbose_name=_("Timestamp"))
    to_address = models.EmailField(verbose_name=_("To address"))
    from_address = models.EmailField(verbose_name=_("From address"))
    subject = models.CharField(max_length=256, verbose_name=_("Subject"))
    body = models.TextField(verbose_name=_("Body"))

    def recipients(self):
        for speaker in self.proposal.speakers():
            yield speaker.email

    def __unicode__(self):
        return self.proposal.title + ' ' + self.timestamp.strftime('%Y-%m-%d %H:%M:%S')

    @property
    def email_args(self):
        return (self.subject, self.body, self.from_address, self.recipients())


def promote_proposal(proposal):
    if hasattr(proposal, "presentation") and proposal.presentation:
        # already promoted
        presentation = proposal.presentation
    else:
        presentation = Presentation(
            title=proposal.title,
            description=proposal.description,
            abstract=proposal.abstract,
            speaker=proposal.speaker,
            section=proposal.section,
            proposal_base=proposal,
        )
        presentation.save()
        for speaker in proposal.additional_speakers.all():
            presentation.additional_speakers.add(speaker)
            presentation.save()

    return presentation


def unpromote_proposal(proposal):
    if hasattr(proposal, "presentation") and proposal.presentation:
        proposal.presentation.delete()


def accepted_proposal(sender, instance=None, **kwargs):
    if instance is None:
        return
    if instance.status == "accepted":
        promote_proposal(instance.proposal)
    else:
        unpromote_proposal(instance.proposal)
post_save.connect(accepted_proposal, sender=ProposalResult)
