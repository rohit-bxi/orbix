import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class MultiSelectTags extends Component {
    static template = "openeducat_library.MultiSelectTags";
    static props = {
        resModel: String,
        selected: Array,
        onChange: Function,
        placeholder: { type: String, optional: true },
    };
    static defaultProps = {
        placeholder: "Search...",
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ query: "", suggestions: [] });
    }

    async loadSuggestions() {
        const excludeIds = this.props.selected.map((rec) => rec.id);
        const domain = this.state.query ? [["name", "ilike", this.state.query]] : [];
        if (excludeIds.length) {
            domain.push(["id", "not in", excludeIds]);
        }
        this.state.suggestions = await this.orm.searchRead(
            this.props.resModel,
            domain,
            ["id", "name"],
            { limit: 8, order: "name" }
        );
    }

    onInput(ev) {
        this.state.query = ev.target.value;
        this.loadSuggestions();
    }

    onFocus() {
        this.loadSuggestions();
    }

    onBlur() {
        setTimeout(() => {
            this.state.suggestions = [];
        }, 150);
    }

    selectSuggestion(rec) {
        this.props.onChange([...this.props.selected, { id: rec.id, name: rec.name }]);
        this.state.query = "";
        this.state.suggestions = [];
    }

    removeTag(id) {
        this.props.onChange(this.props.selected.filter((rec) => rec.id !== id));
    }

    async onKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        const query = this.state.query.trim();
        if (!query) {
            return;
        }
        const existing = this.state.suggestions.find(
            (s) => s.name.toLowerCase() === query.toLowerCase()
        );
        if (existing) {
            this.selectSuggestion(existing);
            return;
        }
        const ids = await this.orm.create(this.props.resModel, [{ name: query }]);
        this.selectSuggestion({ id: ids[0], name: query });
    }
}
