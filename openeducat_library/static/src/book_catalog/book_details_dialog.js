import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

const BOOK_FIELDS = [
    "name", "isbn", "edition", "genre_id", "language", "publish_year",
    "number_of_pages", "shelf_location", "allocation", "description",
    "rating", "total_copies", "available_copies", "status",
    "author_ids", "publisher_ids", "attachment_ids",
];

export class BookDetailsDialog extends Component {
    static template = "openeducat_library.BookDetailsDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        resId: Number,
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ book: null, authors: [], publishers: [], attachments: [] });

        onWillStart(async () => {
            const [book] = await this.orm.read("op.media", [this.props.resId], BOOK_FIELDS);
            this.state.book = book;
            const [authors, publishers] = await Promise.all([
                this.orm.searchRead("op.author", [["id", "in", book.author_ids]], ["id", "name"]),
                this.orm.searchRead("op.publisher", [["id", "in", book.publisher_ids]], ["id", "name"]),
            ]);
            this.state.authors = authors;
            this.state.publishers = publishers;
            if (book.attachment_ids.length) {
                this.state.attachments = await this.orm.searchRead(
                    "ir.attachment", [["id", "in", book.attachment_ids]], ["id", "name", "mimetype"]);
            }
        });
    }

    get authorNames() {
        return this.state.authors.map((rec) => rec.name).join(", ") || "-";
    }

    get publisherNames() {
        return this.state.publishers.map((rec) => rec.name).join(", ") || "-";
    }

    attachmentUrl(attachment) {
        return `/web/content/${attachment.id}?download=true`;
    }
}
