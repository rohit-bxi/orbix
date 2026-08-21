import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { MultiSelectTags } from "./multi_select_tags";

const BOOK_FIELDS = [
    "name", "isbn", "edition", "genre_id", "language", "publish_year",
    "number_of_pages", "shelf_location", "allocation", "description",
    "rating", "total_copies", "author_ids", "publisher_ids", "attachment_ids",
];

export class BookFormDialog extends Component {
    static template = "openeducat_library.BookFormDialog";
    static components = { Dialog, MultiSelectTags };
    static props = {
        close: Function,
        resId: { type: Number, optional: true },
        onSaved: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            name: "",
            isbn: "",
            edition: "",
            genre_id: false,
            language: false,
            publish_year: false,
            number_of_pages: false,
            shelf_location: "",
            allocation: "",
            description: "",
            rating: 0,
            total_copies: 0,
            authors: [],
            publishers: [],
            attachments: [],
            newFile: null,
            genres: [],
            languageOptions: [],
            saving: false,
            errors: {},
        });

        onWillStart(async () => {
            const [genres, fieldsInfo] = await Promise.all([
                this.orm.searchRead("op.media.genre", [], ["id", "name"]),
                this.orm.call("op.media", "fields_get", [["language"]], {
                    attributes: ["selection"],
                }),
            ]);
            this.state.genres = genres;
            this.state.languageOptions = fieldsInfo.language.selection;

            if (this.props.resId) {
                const [book] = await this.orm.read("op.media", [this.props.resId], BOOK_FIELDS);
                Object.assign(this.state, {
                    name: book.name,
                    isbn: book.isbn || "",
                    edition: book.edition || "",
                    genre_id: book.genre_id ? book.genre_id[0] : false,
                    language: book.language,
                    publish_year: book.publish_year || false,
                    number_of_pages: book.number_of_pages || false,
                    shelf_location: book.shelf_location || "",
                    allocation: book.allocation || "",
                    description: book.description || "",
                    rating: book.rating || 0,
                    total_copies: book.total_copies || 0,
                });
                const [authors, publishers] = await Promise.all([
                    this.orm.searchRead("op.author", [["id", "in", book.author_ids]], ["id", "name"]),
                    this.orm.searchRead("op.publisher", [["id", "in", book.publisher_ids]], ["id", "name"]),
                ]);
                this.state.authors = authors;
                this.state.publishers = publishers;
                if (book.attachment_ids.length) {
                    this.state.attachments = await this.orm.searchRead(
                        "ir.attachment", [["id", "in", book.attachment_ids]], ["id", "name"]);
                }
            }
        });
    }

    get title() {
        return this.props.resId ? _t("Edit Book") : _t("Add New Book");
    }

    onNameInput(ev) {
        this.state.name = ev.target.value;
    }

    onGenreChange(ev) {
        this.state.genre_id = ev.target.value ? parseInt(ev.target.value) : false;
    }

    onAuthorsChange = (recs) => {
        this.state.authors = recs;
    };

    onPublishersChange = (recs) => {
        this.state.publishers = recs;
    };

    onPublishYearInput(ev) {
        this.state.publish_year = ev.target.value ? parseInt(ev.target.value) : false;
    }

    onTotalCopiesInput(ev) {
        this.state.total_copies = ev.target.value ? parseInt(ev.target.value) : 0;
    }

    onNumberOfPagesInput(ev) {
        this.state.number_of_pages = ev.target.value ? parseInt(ev.target.value) : false;
    }

    onLanguageChange(ev) {
        this.state.language = ev.target.value || false;
    }

    onShelfLocationInput(ev) {
        this.state.shelf_location = ev.target.value;
    }

    onAllocationInput(ev) {
        this.state.allocation = ev.target.value;
    }

    onDescriptionInput(ev) {
        this.state.description = ev.target.value;
    }

    onCancel() {
        this.props.close();
    }

    onFileChange(ev) {
        const file = ev.target.files[0];
        if (!file) {
            return;
        }
        const reader = new FileReader();
        reader.onload = () => {
            this.state.newFile = {
                name: file.name,
                type: file.type,
                data: reader.result.split(",")[1],
            };
        };
        reader.readAsDataURL(file);
    }

    validate() {
        const errors = {};
        if (!this.state.name) {
            errors.name = _t("Book title is required.");
        }
        if (!this.state.genre_id) {
            errors.genre_id = _t("Please select a genre.");
        }
        if (!this.state.authors.length) {
            errors.authors = _t("Please add at least one author.");
        }
        if (!this.state.publishers.length) {
            errors.publishers = _t("Please add at least one publisher.");
        }
        if (!this.state.total_copies) {
            errors.total_copies = _t("Total copies must be greater than 0.");
        }
        this.state.errors = errors;
        return !Object.keys(errors).length;
    }

    async onSave() {
        if (!this.validate()) {
            this.notification.add(_t("Please fill in all required fields."), { type: "danger" });
            return;
        }
        this.state.saving = true;
        const vals = {
            name: this.state.name,
            isbn: this.state.isbn || false,
            edition: this.state.edition || false,
            genre_id: this.state.genre_id,
            language: this.state.language || false,
            publish_year: this.state.publish_year || false,
            number_of_pages: this.state.number_of_pages || false,
            shelf_location: this.state.shelf_location || false,
            allocation: this.state.allocation || false,
            description: this.state.description || false,
            rating: this.state.rating || 0,
            total_copies: this.state.total_copies,
            author_ids: [[6, 0, this.state.authors.map((rec) => rec.id)]],
            publisher_ids: [[6, 0, this.state.publishers.map((rec) => rec.id)]],
        };
        try {
            let bookId = this.props.resId;
            if (bookId) {
                await this.orm.write("op.media", [bookId], vals);
            } else {
                const ids = await this.orm.create("op.media", [vals]);
                bookId = ids[0];
            }
            if (this.state.newFile) {
                const attachmentIds = await this.orm.create("ir.attachment", [{
                    name: this.state.newFile.name,
                    datas: this.state.newFile.data,
                    mimetype: this.state.newFile.type,
                }]);
                await this.orm.write("op.media", [bookId], {
                    attachment_ids: [[4, attachmentIds[0]]],
                });
            }
            this.props.onSaved();
            this.props.close();
        } catch (error) {
            this.notification.add(
                error.data && error.data.message || _t("Could not save the book."),
                { type: "danger" }
            );
        } finally {
            this.state.saving = false;
        }
    }
}
