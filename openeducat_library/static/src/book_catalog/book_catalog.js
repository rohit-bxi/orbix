import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { BookFormDialog } from "./book_form_dialog";
import { BookDetailsDialog } from "./book_details_dialog";

const PAGE_SIZE = 8;

const LIST_FIELDS = [
    "name", "genre_id", "language", "total_copies", "available_copies",
    "number_of_pages", "rating", "status", "author_ids",
];

export class BookCatalog extends Component {
    static template = "openeducat_library.BookCatalog";

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.state = useState({
            books: [],
            authorNames: {},
            searchTerm: "",
            showFilters: false,
            genreFilter: false,
            languageFilter: false,
            statusFilter: false,
            genres: [],
            languageOptions: [],
            statusOptions: [],
            page: 1,
            total: 0,
            isManager: false,
        });

        onWillStart(async () => {
            const [genres, fieldsInfo, isManager] = await Promise.all([
                this.orm.searchRead("op.media.genre", [], ["id", "name"]),
                this.orm.call("op.media", "fields_get", [["language", "status"]], {
                    attributes: ["selection"],
                }),
                user.hasGroup("openeducat_library.group_op_library"),
            ]);
            this.state.genres = genres;
            this.state.languageOptions = fieldsInfo.language.selection;
            this.state.statusOptions = fieldsInfo.status.selection;
            this.state.isManager = isManager;
            await this.loadBooks();
        });
    }

    get domain() {
        const domain = [];
        if (this.state.searchTerm) {
            domain.push("|");
            domain.push(["name", "ilike", this.state.searchTerm]);
            domain.push(["author_ids.name", "ilike", this.state.searchTerm]);
        }
        if (this.state.genreFilter) {
            domain.push(["genre_id", "=", this.state.genreFilter]);
        }
        if (this.state.languageFilter) {
            domain.push(["language", "=", this.state.languageFilter]);
        }
        if (this.state.statusFilter) {
            domain.push(["status", "=", this.state.statusFilter]);
        }
        return domain;
    }

    get totalPages() {
        return Math.max(1, Math.ceil(this.state.total / PAGE_SIZE));
    }

    get pageNumbers() {
        return Array.from({ length: this.totalPages }, (_, index) => index + 1);
    }

    async loadBooks() {
        const domain = this.domain;
        this.state.total = await this.orm.searchCount("op.media", domain);
        const books = await this.orm.searchRead("op.media", domain, LIST_FIELDS, {
            limit: PAGE_SIZE,
            offset: (this.state.page - 1) * PAGE_SIZE,
            order: "name",
        });
        this.state.books = books;

        const authorIds = [...new Set(books.flatMap((book) => book.author_ids))];
        if (authorIds.length) {
            const authors = await this.orm.searchRead(
                "op.author", [["id", "in", authorIds]], ["id", "name"]);
            this.state.authorNames = Object.fromEntries(
                authors.map((author) => [author.id, author.name]));
        }
    }

    authorNames(book) {
        return book.author_ids.map((id) => this.state.authorNames[id]).filter(Boolean).join(", ") || "-";
    }

    statusLabel(status) {
        const found = (this.state.statusOptions || []).find((opt) => opt[0] === status);
        return found ? found[1] : status;
    }

    genreColorClass(genreId) {
        const palette = ["o_genre_blue", "o_genre_magenta", "o_genre_orange", "o_genre_green", "o_genre_teal", "o_genre_red"];
        return palette[genreId % palette.length];
    }

    onSearchInput(ev) {
        this.state.searchTerm = ev.target.value;
        this.state.page = 1;
        this.loadBooks();
    }

    toggleFilters() {
        this.state.showFilters = !this.state.showFilters;
    }

    onFilterChange() {
        this.state.page = 1;
        this.loadBooks();
    }

    onGenreFilterChange(ev) {
        this.state.genreFilter = ev.target.value ? parseInt(ev.target.value) : false;
        this.onFilterChange();
    }

    onLanguageFilterChange(ev) {
        this.state.languageFilter = ev.target.value || false;
        this.onFilterChange();
    }

    onStatusFilterChange(ev) {
        this.state.statusFilter = ev.target.value || false;
        this.onFilterChange();
    }

    goToPage(page) {
        if (page < 1 || page > this.totalPages) {
            return;
        }
        this.state.page = page;
        this.loadBooks();
    }

    openAddBook() {
        this.dialog.add(BookFormDialog, {
            onSaved: () => this.loadBooks(),
        });
    }

    openEditBook(book) {
        this.dialog.add(BookFormDialog, {
            resId: book.id,
            onSaved: () => this.loadBooks(),
        });
    }

    openBookDetails(book) {
        this.dialog.add(BookDetailsDialog, { resId: book.id });
    }

    deleteBook(book) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete Book"),
            body: _t("Are you sure you want to delete \"%s\"?", book.name),
            confirmLabel: _t("Delete"),
            confirmClass: "btn-danger",
            confirm: async () => {
                await this.orm.unlink("op.media", [book.id]);
                await this.loadBooks();
            },
            cancel: () => {},
        });
    }
}

registry.category("actions").add("book_catalog_client_action", BookCatalog);
