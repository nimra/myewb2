"""myEWB base groups generic views

This file is part of myEWB
Copyright 2009 Engineers Without Borders (Canada) Organisation and/or volunteer contributors
Some code derived from Pinax, copyright 2008-2009 James Tauber and Pinax Team, licensed under the MIT License

Last modified on 2009-08-02
@author Joshua Gorner, Benjamin Best
"""

from django.shortcuts import render_to_response, get_object_or_404
from django.template import RequestContext
from django.http import HttpResponseRedirect, HttpResponseNotFound, Http404
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.utils.datastructures import SortedDict
from django.utils.translation import ugettext_lazy as _
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned

from base_groups.models import BaseGroup, GroupMember, PendingMember, InvitationToJoinGroup, RequestToJoinGroup
from base_groups.forms import GroupMemberForm, EditGroupMemberForm
from base_groups.decorators import own_member_object_required, group_admin_required, visibility_required

@visibility_required()
def members_index(request, group_slug, group_model=None, form_class=None,
                  template_name=None, new_template_name=None):
    
    # handle generic call
    if group_model is None and request.method == 'GET':
        group = get_object_or_404(BaseGroup, slug=group_slug)
        return HttpResponseRedirect(reverse('%s_members_index' % group.model.lower(), kwargs={'group_slug': group_slug}))

    # be RESTful, allow POSTing to the index
    if request.method == 'POST':
        return new_member(request, group_slug, group_model=group_model,
                          form_class=form_class,
                          template_name=new_template_name,
                          index_template_name=template_name)
    
    # get basic objects
    user = request.user    
    group = get_object_or_404(group_model, slug=group_slug)
    
    # only admins can see invitations/requests
    if group.user_is_admin(user):
        members = group.members.all()
    else:
        members = group.get_accepted_members()   # excludes invited / requested members

    # filter by search terms if rovided
    search_terms = request.GET.get('search', '')
    if search_terms:
        members = members.filter(user__profile__name__icontains=search_terms) | \
                        members.filter(user__username__icontains=search_terms) | \
                        members.filter(is_admin=True, admin_title__icontains=search_terms) | \
                        members.filter(user__email__icontains=search_terms)
                        
    # show listing
    return render_to_response(
        template_name,
        {
            'group': group,
            'members': members,
            'is_admin': group.user_is_admin(user),
            'search_terms': search_terms
        },
        context_instance=RequestContext(request),
    )

@visibility_required()
def new_member(request, group_slug, group_model=None, form_class=None,
               template_name=None, index_template_name=None):
    
    # handle generic call
    # XX does this ever happen in practise???
    if group_model is None and request.method == 'GET':
        group = get_object_or_404(BaseGroup, slug=group_slug)
        return HttpResponseRedirect(reverse('%s_new_member' % group.model.lower(), kwargs={'group_slug': group_slug}))    
        
    # load up basic objects
    group = get_object_or_404(group_model, slug=group_slug)
    user = request.user
    
    # why do we exclude admins?
    if group.user_is_member_or_pending(user) and not group.user_is_admin(user):
        request.user.message_set.create(
            message=_("You are already a member, or pending member, of this %(model)s - see below.") % {"model": group_model._meta.verbose_name,})
        return HttpResponseRedirect(reverse('%s_member_detail' % group.model.lower(), kwargs={'group_slug': group_slug, 'username': user.username}))
    
    # we're on the save leg
    if request.method == 'POST':
        # load up form
        form = form_class(request.POST)
        if form.is_valid():
            for singleuser in form.cleaned_data['user']:
                existing_members = group.members.filter(user=singleuser)
            
                # General users can only add themselves as members
                # Users cannot have multiple memberships in the same group
                # TODO: split out invitations/requests into a different process & object
                if existing_members.count() == 0 and (user == singleuser or user.is_staff or group.user_is_admin(user)):
                    member = None
                    if user == singleuser:
                        if group.invite_only and not user.is_staff:     # we ignore group admins since they must already be members
                            member = RequestToJoinGroup() # create a membership request instead
                    
                    if member == None:
                        member = GroupMember()

                    member.group = group
                    member.user = singleuser
                    
                    if isinstance(member, GroupMember) and not (user.is_staff or group.user_is_admin(user)):
                        # General users cannot make themselves admins
                        member.is_admin = False
                        member.admin_title = ""
                    else:
                        member.is_admin = form.cleaned_data['is_admin']
                        member.admin_title = form.cleaned_data['admin_title']
                
                    member.save()
                
            # different returns if it's an ajax call...
            if request.is_ajax():
                response = render_to_response("base_groups/ajax-join.html",
                                              {'group': group},
                                              context_instance=RequestContext(request),
                                             )
            else:
                response =  HttpResponseRedirect(reverse('%s_detail' % group_model._meta.module_name, kwargs={'group_slug': group_slug}))
            return response
            
    else:
        form = form_class()
        
    # either it's a new form, or there's some kind of validation error
    if request.is_ajax():
        response = render_to_response("base_groups/ajax-join.html",
                                      {'group': None},
                                      context_instance=RequestContext(request),
                                     )
    else:
        response = render_to_response(template_name,
                                      {'group': group,
                                       'form': form,
                                       'is_admin': group.user_is_admin(user),
                                      },
                                      context_instance=RequestContext(request),
                                     )
    return response

@visibility_required()
def invite_member(request, group_slug, group_model=None, form_class=None,
               template_name=None, index_template_name=None):
    
    # handle generic call
    # XX does this ever happen in practise???
    if group_model is None and request.method == 'GET':
        group = get_object_or_404(BaseGroup, slug=group_slug)
        return HttpResponseRedirect(reverse('%s_invite_member' % group.model.lower(), kwargs={'group_slug': group_slug}))    
        
    # load up basic objects
    group = get_object_or_404(group_model, slug=group_slug)
    user = request.user
    
    # why do we exclude admins?
    if group.user_is_member_or_pending(user) and not group.user_is_admin(user):
        request.user.message_set.create(
            message=_("You are already a member, or pending member, of this %(model)s - see below.") % {"model": group_model._meta.verbose_name,})
        return HttpResponseRedirect(reverse('%s_member_detail' % group.model.lower(), kwargs={'group_slug': group_slug, 'username': user.username}))
    
    # we're on the save leg
    if request.method == 'POST':
        # load up form
        form = form_class(request.POST)
        if form.is_valid():
            for singleuser in form.cleaned_data['user']:
                existing_members = group.members.filter(user=singleuser)

                if existing_members.count() > 0:
                    request.user.message_set.create(message="%s is already in the group!" % singleuser.visible_name())

                else:
                    member = InvitationToJoinGroup() # another user invited by a group / site admin         
                    member.group = group
                    member.invited_by = request.user
                    member.user = singleuser
                    member.message = form.cleaned_data['message']
                    member.save()
                
                    #request.user.message_set.create(message=_("Invitation sent"))    # why's this choking?
                    request.user.message_set.create(message="Invitation sent to %s" % singleuser.visible_name())

            return HttpResponseRedirect(reverse('%s_detail' % group_model._meta.module_name, kwargs={'group_slug': group_slug}))
            
    else:
        form = form_class()
        
    # either it's a new form, or there's some kind of validation error
    response = render_to_response(template_name,
                                  {'group': group,
                                   'form': form,
                                   'is_admin': group.user_is_admin(user),
                                  },
                                  context_instance=RequestContext(request),
                                 )
    return response

@visibility_required()
def member_detail(request, group_slug, username, group_model=None,
                  form_class=None, template_name=None, edit_template_name=None):
    # handle generic call
    if group_model is None and request.method == 'GET':
        group = get_object_or_404(BaseGroup, slug=group_slug)
        return HttpResponseRedirect(reverse('%s_member_detail' % group.model.lower(), kwargs={'group_slug': group_slug, 'username': username}))    

    # be RESTful.  yada yada yada.
    if request.method == 'POST':
        return edit_member(request, group_slug, username,
                           group_model=group_model, form_class=form_class,
                           template_name=edit_template_name,
                           detail_template_name=template_name)
        
    # retrieve basic objects
    group = get_object_or_404(group_model, slug=group_slug)
    other_user = get_object_or_404(User, username=username)
    if group.user_is_member(other_user):
        member = get_object_or_404(GroupMember, group=group, user=other_user)
    elif group.user_is_pending_member(other_user):
        member = get_object_or_404(PendingMember, group=group, user=other_user)
    else:
        raise Http404

    user = request.user
    
    return render_to_response(template_name,
                              {'group': group,
                               'member': member,
                               'is_admin': group.user_is_admin(user),
                              },
                              context_instance=RequestContext(request),
                             )

@group_admin_required()
def edit_member(request, group_slug, username, group_model=None, form_class=None, template_name=None, detail_template_name=None):
    # handle generic call
    if group_model is None and request.method == 'GET':
        group = get_object_or_404(BaseGroup, slug=group_slug)
        return HttpResponseRedirect(reverse('%s_edit_member' % group.model.lower(), kwargs={'group_slug': group_slug, 'username': username}))         
    
    # grab basic objects
    group = get_object_or_404(group_model, slug=group_slug)
    other_user = get_object_or_404(User, username=username)
    member = get_object_or_404(GroupMember, group=group, user=other_user)
    user = request.user
    
    # saving the object
    member = get_object_or_404(GroupMember, group=group, user=other_user)
    if request.method == 'POST':
        form = form_class(request.POST, instance=member)

        # if all's good, save and redirect
        if form.is_valid():
            member = form.save()
            return HttpResponseRedirect(reverse('%s_members_index' % group.model.lower(), kwargs={'group_slug': group_slug}))    

    # just load up the info and put it in a new form
    else:
        form = form_class(instance=member)
        
    return render_to_response(template_name,
                              {'group': group,
                               'form': form,
                               'member': member,
                               'is_admin': group.user_is_admin(user),
                              },
                              context_instance=RequestContext(request),
                             )

@own_member_object_required()
def delete_member(request, group_slug, username, group_model=None):    
    # handle generic call
    if group_model is None and request.method == 'GET':
        group = get_object_or_404(BaseGroup, slug=group_slug)
        return HttpResponseRedirect(reverse('%s_delete_member' % group.model.lower(), kwargs={'group_slug': group_slug, 'username': username}))
        
    # should only ever really be a POST call here...
    if request.method == 'POST':
        # load up objects
        group = get_object_or_404(group_model, slug=group_slug)
        user = get_object_or_404(User, username=username)
        was_pending = False
        if group.user_is_member(user):
            member = get_object_or_404(GroupMember, group=group, user=user)
        elif group.user_is_pending_member(user):
            member = get_object_or_404(PendingMember, group=group, user=user)
            was_pending = True
        else:
            raise Http404
        
        # delete it.  how, that was hard...
        member.delete()
        
        # response is different for AJAX and normal calls.
        if request.is_ajax():
            response = render_to_response("base_groups/ajax-leave.html",
                                          {'group': group},
                                          context_instance=RequestContext(request),
                                         )
        else:
            if request.user == user:
                if was_pending:
                    request.user.message_set.create(message="Cancelled request")
                else:
                    request.user.message_set.create(message="Left group")
            else:
                if was_pending:
                    request.user.message_set.create(message="Declined request")
                else:
                    request.user.message_set.create(message="Removed member")
                
            response =  HttpResponseRedirect(reverse('%s_detail' % group.model.lower(), kwargs={'group_slug': group_slug,}))
            
    # these are both errors.  it's all in how we display it...
    else:
        if request.is_ajax():
            response = render_to_response("base_groups/ajax-leave.html",
                                          {'group': None},
                                          context_instance=RequestContext(request),
                                         )
        else:
            response = HttpResponseNotFound();
            
    return response
    
def accept_invitation(request, group_slug, username, group_model=BaseGroup):
    # always a POST
    if request.method == 'POST':
        # load up basic objects
        group = get_object_or_404(group_model, slug=group_slug)
        other_user = get_object_or_404(User, username=username)
        invitation = get_object_or_404(InvitationToJoinGroup, group=group, user=other_user)
        
        if request.user.is_authenticated() and other_user == request.user:
            invitation.accept()
        
        request.user.message_set.create(message="Accepted invitation and joined \"%s\"" % group)
        return HttpResponseRedirect(reverse('%s_detail' % group.model.lower(), kwargs={'group_slug': group_slug}))
    else:
        return HttpResponseNotFound()
        
def accept_request(request, group_slug, username, group_model=BaseGroup):
    # always a POST
    if request.method == 'POST':
        # load up basic obejcts
        group = get_object_or_404(group_model, slug=group_slug)
        user = get_object_or_404(User, username=username)
        group_request = get_object_or_404(RequestToJoinGroup, group=group, user=user)
        
        # only admins can approve requests
        if request.user.is_authenticated() and group.user_is_admin(request.user):
            group_request.accept()
        
        return HttpResponseRedirect(reverse('%s_member_detail' % group.model.lower(), kwargs={'group_slug': group_slug, 'username': username}))
    else:
        return HttpResponseNotFound()
