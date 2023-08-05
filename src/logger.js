import { createLogger, format, transports } from 'winston';
import DailyRotateFile from 'winston-daily-rotate-file';

// 创建logger
export const logger = createLogger({
  colorize: true,
  prettyPrint: true,
  format: format.combine(
    format.timestamp({
      format: 'YYYY-MM-DD HH:mm:ss'
    }),
    format.printf(info => {
        return format.colorize().colorize(info.level, `${info.timestamp} ${info.level}: ${info.message}`);
    })
  ),
  transports: [
    new transports.Console(),
    new (DailyRotateFile)({
      filename: 'logs/%DATE%.log',
      datePattern: 'YYYY-MM-DD',
      zippedArchive: true,
      maxSize: '20m',
      maxFiles: '14d'
    })
  ]
});
