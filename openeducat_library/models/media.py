###############################################################################
#
#    OpenEduCat Inc
#    Copyright (C) 2009-TODAY OpenEduCat Inc(<https://www.openeducat.org>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Lesser General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################

from odoo import _, fields, models, api
from odoo.exceptions import ValidationError

LANGUAGE_SELECTION = [
    ('english', 'English'),
    ('hindi', 'Hindi'),
    ('marathi', 'Marathi'),
    ('gujarati', 'Gujarati'),
    ('other', 'Other'),
]


class OpMedia(models.Model):
    _name = "op.media"
    _description = "Media Details"
    _inherit = "mail.thread"
    _order = "name"

    name = fields.Char('Title', size=128, required=True)
    isbn = fields.Char('ISBN Code', size=64)
    tags = fields.Many2many('op.tag', string='Tag(s)')
    author_ids = fields.Many2many(
        'op.author', string='Author(s)', required=True)
    edition = fields.Char('Edition')
    description = fields.Text('Description')
    publisher_ids = fields.Many2many(
        'op.publisher', string='Publisher(s)', required=True)
    course_ids = fields.Many2many('op.course', string='Course')
    movement_line = fields.One2many('op.media.movement', 'media_id',
                                    'Movements')
    subject_ids = fields.Many2many(
        'op.subject', string='Subjects')
    internal_code = fields.Char('Internal Code', size=64)
    queue_ids = fields.One2many('op.media.queue', 'media_id', 'Media Queue')
    unit_ids = fields.One2many('op.media.unit', 'media_id', 'Units')
    media_type_id = fields.Many2one('op.media.type', 'Media Type')
    active = fields.Boolean(default=True)
    genre_id = fields.Many2one('op.media.genre', string='Genre', required=True)
    publish_year = fields.Integer('Publish Year')
    number_of_pages = fields.Integer('Number of Pages')
    language = fields.Selection(LANGUAGE_SELECTION, string='Language')
    shelf_location = fields.Char('Shelf Location')
    allocation = fields.Char('Allocation', help='Class-Section, etc.')
    rating = fields.Float('Rating')
    total_copies = fields.Integer('Total Copies', default=0)
    available_copies = fields.Integer(
        'Available Copies', compute='_compute_copies', store=True)
    status = fields.Selection(
        [('unavailable', 'Unavailable'),
         ('limited', 'Limited'),
         ('available', 'Available')],
        string='Status', compute='_compute_copies', store=True)
    attachment_ids = fields.Many2many(
        'ir.attachment', 
        string="Attachments"
    )
    # Computed Binary and Filename fields linked to the PDF
    attachment_pdf = fields.Binary(
        string="PDF File", 
        compute='_compute_attachment_pdf', 
        store=True
    )
    pdf_filename = fields.Char(
        string="PDF Filename", 
        compute='_compute_attachment_pdf', 
        store=True
    )

    @api.depends('attachment_ids', 'attachment_ids.datas', 'attachment_ids.name', 'attachment_ids.mimetype')
    def _compute_attachment_pdf(self):
        for record in self:
            # Find the first PDF file in the attachment list
            pdf_att = record.attachment_ids.filtered(
                lambda att: att.mimetype == 'application/pdf' or (att.name and att.name.lower().endswith('.pdf'))
            )
            
            if pdf_att:
                # Take the first matching PDF attachment
                attachment = pdf_att[0]
                record.attachment_pdf = attachment.datas
                record.pdf_filename = attachment.name
            else:
                record.attachment_pdf = False
                record.pdf_filename = False

    _unique_name_isbn = models.Constraint('unique(isbn)',
                                          'ISBN code must be unique per media!')

    _unique_name_internal_cod = models.Constraint(
        'unique(internal_code)', 'Internal Code must be unique per media!')

    @api.depends('unit_ids.state', 'unit_ids.active', 'total_copies')
    def _compute_copies(self):
        for record in self:
            available = len(record.unit_ids.filtered(
                lambda unit: unit.state == 'available'))
            record.available_copies = available
            total = record.total_copies or len(record.unit_ids)
            if available <= 0:
                record.status = 'unavailable'
            elif total and available <= total * 0.3:
                record.status = 'limited'
            else:
                record.status = 'available'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.total_copies:
                record._sync_media_units(record.total_copies)
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'total_copies' in vals:
            for record in self:
                record._sync_media_units(record.total_copies)
        return res

    def _sync_media_units(self, total_copies):
        self.ensure_one()
        current_units = self.unit_ids
        diff = total_copies - len(current_units)
        if diff > 0:
            vals_list = [{
                'name': _('%(book)s - Copy %(number)s') % {
                    'book': self.name, 'number': len(current_units) + i + 1},
                'media_id': self.id,
            } for i in range(diff)]
            self.env['op.media.unit'].create(vals_list)
        elif diff < 0:
            to_archive_count = -diff
            available_units = current_units.filtered(
                lambda unit: unit.state == 'available')
            if len(available_units) < to_archive_count:
                raise ValidationError(_(
                    'Cannot reduce Total Copies below the number of copies '
                    'currently issued.'))
            available_units[:to_archive_count].write({'active': False})
