/* @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { Component, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ensureJQuery } from '@web/core/ensure_jquery';

class CaptureEmployeeImage extends Component {
    static template = "CaptureEmployeeImage";

    setup() {
        super.setup();
        const params = this.props.action.params;
        this.resModel = params.res_model || "hr.employee";
        this.resId = params.res_id || params.employee_id || params.active_id;
        this.orm = useService("orm");
        this.action = useService("action");
        try {
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                alert("Unable to access the camera");
                this.env.config.historyBack();
            } else {
                onMounted(async () => {
                    await ensureJQuery();
                    this._start_video_stream();
                    this._bind_events();
                })
            }
        }
        catch (error) {
            console.log(error);
        }
    }

    _start_video_stream() {
        const self = this;
        setTimeout(() => {
            // Ask for HD: this photo is also the person's face for face login,
            // which needs the face at least 80 px wide.
            navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 } } })
                .then(function (stream) {
                    var video = document.getElementById('video');
                    video.srcObject = stream;
                })
                .catch(function (err) {
                    self._stop_stream();
                    alert("Unable to access the camera");
                    self.env.config.historyBack();
                });
        }, 500);
    }

    _bind_events() {
        $('#btn-close').on('click', this._on_close.bind(this));
        $('#btn-click').on('click', this._on_capture.bind(this));
        $('#btn-close-sub').on('click', this._on_close.bind(this));
    }

    _on_capture() {
        try {
            const self = this;

            var video = document.getElementById('video');
            var canvas = document.getElementById('canvas');
            var context = canvas.getContext('2d');

            // Keep the camera's own size and aspect ratio (at most 1280 px):
            // a fixed 320x240 made faces too small (and stretched on
            // widescreen cameras) for face login.
            const sourceWidth = video.videoWidth || 640;
            const sourceHeight = video.videoHeight || 480;
            const scale = Math.min(1, 1280 / Math.max(sourceWidth, sourceHeight));
            const targetWidth = Math.round(sourceWidth * scale);
            const targetHeight = Math.round(sourceHeight * scale);

            canvas.width = targetWidth;
            canvas.height = targetHeight;

            context.drawImage(video, 0, 0, targetWidth, targetHeight);

            var imageData = canvas.toDataURL('image/jpeg', 0.92);

            this.orm.call(this.resModel, 'register_face', [this.resId, imageData])
            .then(function (result) {
                self._on_close();
            });
        } catch {
            this._on_close();
        }
    }

    _stop_stream() {
        var video = document.getElementById('video');
        if (video && video.srcObject) {
            let tracks = video.srcObject.getTracks();
            tracks.forEach(track => track.stop());
            video.srcObject = null;
        }
    }

    _on_close() {
        this._stop_stream();
        this.env.config.historyBack();
    }
    
}

registry.category("actions").add("new_employee_image", CaptureEmployeeImage);
