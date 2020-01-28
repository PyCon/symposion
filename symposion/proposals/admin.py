from django.contrib import admin

# from symposion.proposals.actions import export_as_csv_action
from symposion.proposals.models import AdditionalSpeaker, ProposalSection, ProposalKind


# admin.site.register(Proposal,
#     list_display = [
#         "id",
#         "title",
#         "speaker",
#         "speaker_email",
#         "kind",
#         "audience_level",
#         "cancelled",
#     ],
#     list_filter = [
#         "kind__name",
#         "result__accepted",
#     ],
#     actions = [export_as_csv_action("CSV Export", fields=[
#         "id",
#         "title",
#         "speaker",
#         "speaker_email",
#         "kind",
#     ])]
# )

admin.site.register(ProposalSection)
admin.site.register(ProposalKind)

class AdditionalSpeakerAdmin(admin.ModelAdmin):
    list_display = ['speaker', 'proposalbase', 'status']
    list_filter = ['status']
    search_fields = ['proposalbase']

admin.site.register(AdditionalSpeaker, AdditionalSpeakerAdmin)
