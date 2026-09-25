/**
 * 通用滑块验证码管理器 (Node.js 版)
 *
 * 适合服务端滑块验证流程：获取验证码 -> 计算 offset -> 提交校验 -> 失败重试。
 */

class SliderCaptchaManager {
    constructor(config = {}) {
        this.maxAttempts = config.maxAttempts || 50;
        this.retryDelayMs = config.retryDelayMs || 1000;
        this.ocrServer = config.ocrServer || process.env.OCR_SERVER || '';
        this.fixedOffset = config.fixedOffset ?? null;
        this.debug = config.debug ?? true;
    }

    log(...args) {
        if (this.debug) {
            console.log('[SliderCaptchaManager]', ...args);
        }
    }

    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    async execute(fetchCaptchaFn, verifyCaptchaFn) {
        if (typeof fetchCaptchaFn !== 'function') {
            throw new TypeError('fetchCaptchaFn 必须是函数');
        }
        if (typeof verifyCaptchaFn !== 'function') {
            throw new TypeError('verifyCaptchaFn 必须是函数');
        }

        for (let attempt = 1; attempt <= this.maxAttempts; attempt++) {
            this.log(`第 ${attempt}/${this.maxAttempts} 次尝试`);
            try {
                const captchaData = await fetchCaptchaFn();
                const captchaId = captchaData && (captchaData.id || captchaData.captcha_id);
                if (!captchaId) {
                    throw new Error('获取验证码结果未包含 id 或 captcha_id');
                }

                const offset = await this.resolveOffset(captchaData);
                const verifyResult = await verifyCaptchaFn(captchaId, offset, captchaData);
                if (verifyResult !== false) {
                    this.log('验证通过');
                    return verifyResult || true;
                }
                this.log('验证函数返回 false，准备重试');
            } catch (error) {
                this.log(`本轮异常: ${error.message}`);
            }
            await this.delay(this.retryDelayMs);
        }

        throw new Error(`验证码验证失败，已达最大尝试次数 (${this.maxAttempts})`);
    }

    async resolveOffset(captchaData) {
        if (this.fixedOffset !== null) {
            return this.fixedOffset;
        }
        if (captchaData.bgImageBase64 && captchaData.sliderImageBase64) {
            const offset = await this.getOffsetFromOCR(captchaData.bgImageBase64, captchaData.sliderImageBase64);
            if (offset !== null && offset !== undefined) {
                return offset;
            }
        }
        this.log('未配置 fixedOffset 且 OCR 信息不足，使用 0 作为兜底 offset');
        return 0;
    }

    async getOffsetFromOCR(bgBase64, sliderBase64) {
        if (!this.ocrServer) {
            this.log('未配置 OCR_SERVER，无法调用 OCR 服务');
            return null;
        }

        let axios;
        try {
            axios = require('axios');
        } catch (error) {
            throw new Error('使用 OCR 服务需要先在 js 目录执行 npm install 安装 axios');
        }

        const payload = {
            target: this.stripDataUri(sliderBase64),
            background: this.stripDataUri(bgBase64)
        };

        try {
            const resp = await axios.post(`${this.ocrServer}/api/ocr/slider`, payload, {
                headers: { 'Content-Type': 'application/json' },
                timeout: 10000
            });
            const data = resp.data || {};
            const target = data.target || data.data?.target;
            const x = Array.isArray(target) ? target[0] : (target && target.x) || data.x;
            if (x !== undefined && x !== null) {
                this.log(`OCR 识别 offset=${x}`);
                return x;
            }
            this.log(`OCR 返回格式未匹配: ${JSON.stringify(data)}`);
            return null;
        } catch (error) {
            this.log(`OCR 请求失败: ${error.message}`);
            return null;
        }
    }

    stripDataUri(value) {
        return String(value || '').replace(/^data:image\/\w+;base64,/, '');
    }
}

module.exports = SliderCaptchaManager;
