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

from logging import info

from .test_classroom_common import TestClassroomCommon


class TestClassroom(TestClassroomCommon):

    def setUp(self):
        super(TestClassroom, self).setUp()

    def test_case_classroom_1(self):
        # Builds its own classroom rather than searching for demo data,
        # which a database created without demo records doesn't have.
        course = self.env['op.course'].create({'name': 'Classroom Course', 'code': 'CLR-C1'})
        batch = self.env['op.batch'].create({
            'name': 'Classroom Batch', 'code': 'CLR-B1', 'course_id': course.id,
            'start_date': '2026-01-01', 'end_date': '2026-12-31',
        })
        record = self.op_classroom.create({
            'name': 'Room 101', 'code': 'CLR-101', 'capacity': 40,
            'course_id': course.id, 'batch_id': batch.id,
        })
        info('      Class Name: %s' % record.name)
        self.assertEqual((record.capacity, record.course_id), (40, course))
        # Changing the course clears the section.
        record.onchange_course()
        self.assertFalse(record.batch_id)


class TestAsset(TestClassroomCommon):

    def setUp(self):
        super(TestAsset, self).setUp()

    def test_case_1_asset(self):
        categ = self.env.ref('product.product_category_all', raise_if_not_found=False) or \
            self.env['product.category'].search([], limit=1)
        uom = self.env.ref('uom.product_uom_unit', raise_if_not_found=False) or \
            self.env['uom.uom'].search([], limit=1)
        classroom = self.env.ref('openeducat_classroom.op_classroom_1', raise_if_not_found=False) or \
            self.env['op.classroom'].search([], limit=1)
            
        product = self.env['product.product'].create({
            'default_code': 'FIFO',
            'name': 'Chairs',
            'categ_id': categ.id,
            'list_price': 100.0,
            'standard_price': 70.0,
            'uom_id': uom.id,
            'description': 'FIFO Ice Cream',
        })
        
        # We need a classroom to link the asset to
        if not classroom:
            classroom = self.env['op.classroom'].create({
                'name': 'Test Classroom',
                'code': 'TCR-01',
                'capacity': 30
            })

        assets = self.op_asset.create({
            'asset_id': classroom.id,
            'product_id': product.id,
            'code': 1,
            'product_uom_qty': 11
        })
        for record in assets:
            info('      Asset Name: %s' % record.asset_id.name)
            info('      Product Name : %s' % record.product_id.name)
            info('      Product Quantity : %s' % record.product_uom_qty)
