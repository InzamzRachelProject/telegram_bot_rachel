import nodemon from 'nodemon';

nodemon({
  script: 'index.js', // 替换为你的入口文件名
  ext: 'js', // 监听的文件扩展名
  ignore: ['node_modules/'], // 忽略的文件夹
  delay: 600, // 延迟重启的时间
  watch: ['src/', 'index.js'] // 替换为需要监视的文件夹或文件
}).on('restart', () => {
  console.log('应用程序发生变动，正在重启...');
});