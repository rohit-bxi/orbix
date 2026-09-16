# -*- coding: utf-8 -*-
from odoo.http import request
from odoo.addons.website_slides.controllers.main import WebsiteSlides


class WebsiteSlidesClassSection(WebsiteSlides):

    def slides_channel_values(self, slide_category=None, slug_tags=None, my=0, page=None, page_size=12, **post):
        render_values = super().slides_channel_values(
            slide_category=slide_category, slug_tags=slug_tags, my=my, page=page, page_size=page_size, **post)

        class_id = post.get('class_id')
        section_id = post.get('section_id')
        search_class = request.env['elearning.class'].sudo()
        search_section = request.env['elearning.section'].sudo()
        if class_id:
            search_class = search_class.browse(int(class_id)).exists()
        if section_id:
            search_section = search_section.browse(int(section_id)).exists()
            if search_section and not search_class:
                search_class = search_section.class_id

        channels = render_values.get('channels')
        if search_section:
            channels = channels.filtered(lambda c: c.section_id == search_section)
        elif search_class:
            channels = channels.filtered(lambda c: c.class_id == search_class)

        render_values.update({
            'channels': channels,
            'search_count': len(channels),
            'elearning_classes': request.env['elearning.class'].sudo().search(
                [('website_published', '=', True)]),
            'search_class': search_class,
            'search_section': search_section,
        })
        return render_values
